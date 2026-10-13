from textwrap import dedent

from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import Connection, dag, task
from boilerplate import (
    GRAPH_BASE_IRI,
    PREFIXES,
    PROV_BASE_IRI,
    get_jobs,
    job_failed,
    jobs_done,
)
from common_context import get_cc

cc, cc_source = get_cc()

## Uses the following connections
# sparql_update_default: sparql-update-connection-secret
# s3_default: s3-connection-secret

# Define secrets - reference k8s secrets by connection ID label
secret_sparql_update_default = Secret(
    "env", "SECRET_SPARQL_UPDATE_DEFAULT", "sparql-update-connection-secret", "value"
)
secret_s3_default = Secret("env", "SECRET_S3_DEFAULT", "s3-connection-secret", "value")

PROV_IRI = f"<{PROV_BASE_IRI}title-extract-warc:v1>"
JOB_TYPE_IRI = "dalajobs:TitledataExtractJob"


@dag(
    schedule=None,  # "@once"
    description="Extract Titel Data for Websites from WARC Payload",
    tags=["wacli"],
)
def s3_kubernetes_titledata_extract_job():

    @task.kubernetes(
        # image="ghcr.io/white-gecko/payload2rdf:main-s3",
        image="ghcr.io/white-gecko/payload2rdf@sha256:176de54ccee723d7987191cb2a0aa5e0a5e760c6d2baf41761f0d130598a01d9",
        secrets=[secret_sparql_update_default, secret_s3_default],
        env_vars={
            "GRAPH_BASE_IRI": GRAPH_BASE_IRI,
        },
        do_xcom_push=True,
        on_failure_callback=job_failed,
        pod_template_dict={
            "spec": {
                "containers": [
                    {
                        "name": "base",
                        "resources": {
                            "limits": {"cpu": "100m", "memory": "128Mi"},
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                        },
                    },
                ]
            }
        },
    )
    def titledata_extract(cc_source: str, job: dict):
        import os

        from payload2rdf.extract import extract_metadata
        from payload2rdf.mapping import map_metadata_to_graph
        from payload2rdf.warc_reader import read_html_payload
        from rdflib import Graph
        from rdflib.namespace import Namespace
        from s3fs import S3FileSystem

        exec_locals = {}
        exec(cc_source, locals=exec_locals)  # noqa: S102
        cc = exec_locals["common_context"]

        sparql_update_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_SPARQL_UPDATE_DEFAULT"),
            conn_id="sparql_update_default",
        )
        s3_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_S3_DEFAULT"), conn_id="s3_default"
        )

        cc.set_boto_env(s3_conn, os.environ)

        s3 = S3FileSystem(config_kwargs={"retries": {"mode": "adaptive"}})

        graph_base_iri = os.environ["GRAPH_BASE_IRI"]

        print(
            f"I will now download the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), and extract the title from the contained website. ({job['job_iri']})."
        )

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"

        print("start title data extraction")

        select_record_id = f"<{job['record_id']}>"
        bibo_website = job["bibo_website"]
        print(f"look for: {bibo_website} in record {select_record_id}")

        record_graph = Graph()
        with s3.open(path_in_s3fs, "rb") as stream_in:
            for _, target_uri, html_payload in read_html_payload(
                stream_in, select_record_id
            ):
                metadata = extract_metadata(target_uri, html_payload)
                map_metadata_to_graph(record_graph, bibo_website, metadata)

        print("end title data extraction")
        print("start add title data to graph")

        WAG = Namespace(graph_base_iri)
        cc.sparql_update_graph(
            conn=sparql_update_conn, add_graph=record_graph, identifier=WAG.warc
        )

        print("end add title data to graph")

        return job

    @task(trigger_rule="all_done")
    def register_files(job: dict):
        sparql_update_conn = Connection.get("sparql_update_default")

        file_update = (
            PREFIXES
            + """
        INSERT DATA {
            GRAPH wag:data {
        """
            + f"<{job['source_file']}> wal:fileStatus filestatus:titledata_extracted."
            + """
            }
        }
        """
        )

        # """
        #     GRAPH wag:prov {
        # """ + "\n".join(
        #     [
        #         f"<{file_iri}> prov:wasGeneratedBy <{job['job_iri']}> ; prov:wasAttributedTo {PROV_IRI}; prov:wasDerivedFrom <{job['source_file']}> ."
        #     ]
        # ) + """
        # }
        # """

        r = cc.sparql_update(sparql_update_conn, file_update)

        print(r)
        print(r.text)

        r.raise_for_status()
        return job

    triple_pattern = dedent("""
    ?source_file wal:filename ?source_filename ;
        wal:bucket ?source_bucket .

    ?bibo_website a bibo:Website ;
        foaf:primaryTopic ?seedUrl .

    ?snapshot a lv:ArchivedWebPage ;
        # The relation from the ?snapshot to the ?seed_request record should be further specified
        # as crawl record or something.
        dc:relation ?seed_request, ?source_file ;
        dct:isPartOf ?bibo_website ;
        foaf:primaryTopic ?seedUrl .

    ?seed_request a dowarc:WARCrecord ;
        dowarc:WARC-Target-URI ?seedUrl ;
        dowarc:WARC-Type "request" ;
        dowarc:WARC-Concurrent-To ?response .

    ?response a dowarc:WARCrecord ;
        dowarc:WARC-Type "response" ;
        dowarc:WARC-Record-ID ?record_id .
    """)

    jobs_done(
        register_files.expand(
            job=titledata_extract.partial(cc_source=cc_source).expand(
                job=get_jobs(
                    [
                        "source_file",
                        "source_filename",
                        "source_bucket",
                        "record_id",
                        "bibo_website",
                    ],
                    JOB_TYPE_IRI,
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )


s3_kubernetes_titledata_extract_job()
