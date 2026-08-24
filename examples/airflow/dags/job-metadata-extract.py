from airflow.sdk import dag, task
from airflow.providers.cncf.kubernetes.secret import Secret
from boilerplate import get_jobs, jobs_done, jobs_failed

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

PROV_IRI = "https://webarchiv.dnb.de/workflow/metadata-extract-warc/v1"


@dag(
    schedule=None,  # "@once"
    description="Extract Structured WARC Metadata",
    tags=["wacli"],
)
def s3_kubernetes_metadata_extract_job():

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
        # image="ghcr.io/white-gecko/warc-metadata2rdf:main-s3",
        image="ghcr.io/white-gecko/warc-metadata2rdf@sha256:61c57230da9f72178b78dd11a0910c2b0ef0d08f093d05b3046467a94838b9df",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": "http://webarchive-versitygw:7070",
            "AWS_DEFAULT_REGION": "eu-central-1",
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
    def metadata_extract(job: dict):
        import os

        from rdflib import Graph, URIRef
        from rdflib.namespace import Namespace
        from rdflib.plugins.stores.sparqlstore import SPARQLUpdateStore
        from s3fs import S3FileSystem
        from warcmetadata.extraction import extract_metadata_simple
        from warcmetadata.utils import get_seed_record, guess_seed_request

        s3 = S3FileSystem(config_kwargs={"retries": {"mode": "adaptive"}})
        # How could a socket.gaierror be handled propperly

        sparql_update_endpoint = os.environ["SPARQL_UPDATE_ENDPOINT"]

        print(
            f"I will now download the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), and extract its metadata. ({job['job_iri']})."
        )

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"

        print("start metadata extraction")

        with s3.open(path_in_s3fs, "rb") as stream_in:
            graph = extract_metadata_simple(stream_in, URIRef(job['source_file']))
            seed_graph = get_seed_record(graph, **guess_seed_request(graph))

        print("end metadata extraction")
        print("start add metadata to graph")

        wa = Namespace("https://webarchiv.dnb.de/")

        store = SPARQLUpdateStore(update_endpoint=sparql_update_endpoint, auth=("admin", "admin"))
        remote_graph = Graph(store=store, identifier=wa.warc)
        remote_graph += seed_graph

        print("end add metadata to graph")

        return job


    @task(trigger_rule="all_done")
    def register_files(job: dict):
        import requests

        file_update = (
            """
        PREFIX wa: <https://webarchiv.dnb.de/>
        PREFIX wal: <https://d-nb.info/standards/elementset/wal#>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX ex: <https://example.org/>

        INSERT DATA {
            GRAPH wa:data {
        """
            + f'<{job['source_file']}> wal:fileStatus ex:metadata_extracted.'
            + """
            }
        }
        """
        )


        # """
        #     GRAPH wa:prov {
        # """ + "\n".join(
        #     [
        #         f"<{file_iri}> prov:wasGeneratedBy <{job['job_iri']}> ; prov:wasAttributedTo <{PROV_IRI}>; prov:wasDerivedFrom <{job['source_file']}> ."
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
    """

    jobs_done(
        register_files.expand(
            job=metadata_extract.expand(
                job=get_jobs(
                    ["source_file", "source_filename", "source_bucket"],
                    "wal:MetadataExtractJob",
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )


s3_kubernetes_metadata_extract_job()
