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
from boilerplate import metadataextract_job_asset as job_asset
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

JOB_IRI_LOCAL_PART = "MetadataExtractJob"

PROV_IRI = f"<{PROV_BASE_IRI}metadata-extract-warc:v1>"
JOB_TYPE_QNAME = "dalajobs:" + JOB_IRI_LOCAL_PART


@dag(
    schedule=job_asset,  # "@once"
    description="Extract Structured WARC Metadata",
    tags=["wacli"],
)
def s3_kubernetes_metadata_extract_job():

    @task.kubernetes(
        # image="ghcr.io/white-gecko/warc-metadata2rdf:main-s3",
        image="ghcr.io/white-gecko/warc-metadata2rdf@sha256:61c57230da9f72178b78dd11a0910c2b0ef0d08f093d05b3046467a94838b9df",
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
                            "limits": {"cpu": "100m", "memory": "256Mi"},
                            "requests": {"cpu": "100m", "memory": "256Mi"},
                        },
                    },
                ]
            }
        },
    )
    def metadata_extract(cc_source: str, job: dict):
        import os

        from rdflib import URIRef
        from rdflib.namespace import Namespace
        from s3fs import S3FileSystem
        from warcmetadata.extraction import extract_metadata_simple
        from warcmetadata.utils import get_seed_record, guess_seed_request

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
        # How could a socket.gaierror be handled propperly

        graph_base_iri = os.environ["GRAPH_BASE_IRI"]

        print(
            f"I will now download the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), and extract its metadata. ({job['job_iri']})."
        )

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"

        print("start metadata extraction")

        # This is the current implementation for the OIA files, where we guess the seed record from a WARC file under the assumption
        # that we have one crawl per file with one seed.
        # TODO: once we also have crawl jobs, we will know the seed urls from the crawl jobs and somehow have to get the conclusion to the respective records.

        with s3.open(path_in_s3fs, "rb") as stream_in:
            graph = extract_metadata_simple(stream_in, URIRef(job["source_file"]))
            seed_graph = get_seed_record(graph, **guess_seed_request(graph))

        print("end metadata extraction")
        print("start add metadata to graph")

        WAG = Namespace(graph_base_iri)
        cc.sparql_update_graph(
            conn=sparql_update_conn, add_graph=seed_graph, identifier=WAG.warc
        )

        print("end add metadata to graph")

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
            + f"<{job['source_file']}> wal:fileStatus filestatus:metadata_extracted."
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

    triple_pattern = """
    ?source_file wal:filename ?source_filename ;
        wal:bucket ?source_bucket .
    """

    jobs_done(
        register_files.expand(
            job=metadata_extract.partial(cc_source=cc_source).expand(
                job=get_jobs(
                    ["source_file", "source_filename", "source_bucket"],
                    JOB_TYPE_QNAME,
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )


s3_kubernetes_metadata_extract_job()
