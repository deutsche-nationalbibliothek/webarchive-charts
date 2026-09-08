from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task
from boilerplate import PREFIXES, PROV_BASE_IRI, get_jobs, jobs_done, jobs_failed

secret_env_access_key = Secret(
    "env", "AWS_ACCESS_KEY_ID", "webarchive-versitygw-credentials", "rootAccessKeyId"
)
secret_env_secret_access_key = Secret(
    "env",
    "AWS_SECRET_ACCESS_KEY",
    "webarchive-versitygw-credentials",
    "rootSecretAccessKey",
)

sparql_update_endpoint = "http://webarchive-fuseki:3030/ds/update"
sparql_update_auth_tuple = ("admin", "admin")

aws_endpoint_url_s3 = "http://webarchive-versitygw:7070"
aws_default_region = "eu-central-1"

PROV_IRI = f"<{PROV_BASE_IRI}title-extract-warc:v1>"
JOB_TYPE_IRI = "dalajobs:TitleExtractJob"


@dag(
    schedule=None,  # "@once"
    description="Extract Titel Data for Websites from WARC Payload",
    tags=["wacli"],
)
def s3_kubernetes_titledata_extract_job():

    def job_failed(context):
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("job_failed was called")
        print(context)
        task_instance = context["task_instance"]
        # Can we get remote_pod from the exception or from the task_instance?
        print(task_instance)
        job_iri = task_instance.xcom_pull(key="job")
        print(f"job {job_iri} failed")
        exception = context.get("exception")
        # We want to get from AirflowException > remote_pod.status.container_statuses[name=base].state.terminated.reason
        # if AirflowException
        import json
        remote_pod_string = "".join(exception.args.splitlines()[1:])
        print(remote_pod_string)
        remote_pod = json.loads(remote_pod_string)
        print(remote_pod)

        # if ApiException
        # TODO get Reason, HTTP response headers, and HTTP response body

        print(f"job_iri: {job_iri}")
        jobs_failed([{"job_iri": job_iri}])

    @task.kubernetes(
        # image="ghcr.io/white-gecko/payload2rdf:main-s3",
        image="ghcr.io/white-gecko/payload2rdf@sha256:176de54ccee723d7987191cb2a0aa5e0a5e760c6d2baf41761f0d130598a01d9",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": aws_endpoint_url_s3,
            "AWS_DEFAULT_REGION": aws_default_region,
            "SPARQL_UPDATE_ENDPOINT": sparql_update_endpoint
        },
        do_xcom_push=True,
        on_failure_callback=job_failed,
        pod_template_dict={
            "spec": {
                "containers": [
                    {
                        "name": "base",
                        "resources": {
                            "limits": {"cpu": "100m", "memory": "512Mi"},
                            "requests": {"cpu": "100m", "memory": "512Mi"},
                        },
                    },
                ]
            }
        },
    )
    def titledata_extract(job: dict):
        import os

        from payload2rdf.extract import extract_metadata
        from payload2rdf.mapping import map_metadata_to_graph
        from payload2rdf.warc_reader import read_html_payload
        from rdflib import Graph
        from rdflib.namespace import Namespace
        from rdflib.plugins.stores.sparqlstore import SPARQLUpdateStore
        from s3fs import S3FileSystem

        s3 = S3FileSystem(config_kwargs={"retries": {"mode": "adaptive"}})
        # How could a socket.gaierror be handled propperly

        sparql_update_endpoint = os.environ["SPARQL_UPDATE_ENDPOINT"]

        print(
            f"I will now download the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), and extract the title from the contained website. ({job['job_iri']})."
        )

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"

        print("start title data extraction")

        # TODO get the record_id and bibo_website_uri
        select_record_id = "<urn:uuid:…>"
        bibo_website = "https://…"

        record_graph = Graph()
        with s3.open(path_in_s3fs, "rb") as stream_in:
            for _, target_uri, html_payload in read_html_payload(
                stream_in, select_record_id
            ):
                metadata = extract_metadata(target_uri, html_payload)
                map_metadata_to_graph(record_graph, bibo_website, metadata)

        print("end title data extraction")
        print("start add title data to graph")

        wa = Namespace("https://webarchiv.dnb.de/")

        store = SPARQLUpdateStore(update_endpoint=sparql_update_endpoint, auth=sparql_update_auth_tuple)
        remote_graph = Graph(store=store, identifier=wa.warc)
        remote_graph += record_graph

        print("end add title data to graph")

        return job


    @task(trigger_rule="all_done")
    def register_files(job: dict):
        import requests

        file_update = (
            PREFIXES + """
        INSERT DATA {
            GRAPH wag:data {
        """
            + f'<{job['source_file']}> wal:fileStatus filestatus:title_extracted.'
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

        r = requests.post(
            sparql_update_endpoint,
            auth=("admin", "admin"),
            headers={
                "Accept": "application/sparql-results+json,*/*;q=0.9",
                "Content-Type": "application/sparql-update",
            },
            data=file_update,
        )

        print(r)
        print(r.text)

        r.raise_for_status()
        return job


    triple_pattern = """
    ?source_file wal:filename ?source_filename ;
        wal:bucket ?source_bucket .

    ?bibo_website a bibo:Website .

    ?snapshot a lv:ArchivedWebPage ;
        dc:relation ?warcinfo, ?source_file ; # The relation from the ?snapshot to the ?warcinfo record should be further specified as crawl record or something. And also a direct reference to the seed request record of the crawl would be nice.
        dct:isPartOf ?bibo_website .

    ?record a dowarc:WARCrecord ;
        dowarc:WARC-Warcinfo-ID warcinfo ;
        dowarc:WARC-Type "response" ;
        dowarc:WARC-Record-ID ?record_id .
    """

    jobs_done(
        register_files.expand(
            job=titledata_extract.expand(
                job=get_jobs(
                    ["source_file", "source_filename", "source_bucket", "record_id", "bibo_website"],
                    JOB_TYPE_IRI,
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )


s3_kubernetes_titledata_extract_job()
