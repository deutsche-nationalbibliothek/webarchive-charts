from airflow.sdk import dag, task
from airflow.providers.cncf.kubernetes.secret import Secret
from boilerplate import get_jobs, jobs_done

secret_env_access_key = Secret(
    "env", "AWS_ACCESS_KEY_ID", "airflow-versitygw-credentials", "rootAccessKeyId"
)
secret_env_secret_access_key = Secret(
    "env",
    "AWS_SECRET_ACCESS_KEY",
    "airflow-versitygw-credentials",
    "rootSecretAccessKey",
)

sparql_update_endpoint = (
    "http://airflow-fuseki.default.svc.cluster.local:3030/ds/update"
)

TARGET_BUCKET_NAME = "waingest"

ARAS_REST_BASE = "http://etc.dnb.de/aras/"
ARAS_REPO = "warc"

PROV_IRI = "https://example.org/oia-duesseldorf/oGet"


@dag(
    schedule=None,  # "@once"
    description="A k8n dag",
    tags=["wacli"],
)
def s3_kubernetes_aras_pull_job():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/aras-py:main-s3",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": "http://airflow-versitygw.default.svc.cluster.local:7070",
            "AWS_DEFAULT_REGION": "eu-central-1",
        },
    )
    def aras_download(job: dict):
        import s3fs
        from io import DEFAULT_BUFFER_SIZE
        from aras_py.run import get_stream

        # load with aras-py and write to s3

        s3 = s3fs.S3FileSystem()

        try:
            s3.mkdir(TARGET_BUCKET_NAME, create_parents=True)
        except FileExistsError:
            pass

        print(
            f"I will now download the files for {job['idn']} and upload them to the s3 bucket {TARGET_BUCKET_NAME}. ({job['job_iri']})."
        )

        stream_iter = get_stream(ARAS_REST_BASE, ARAS_REPO, job["idn"])

        job["files"] = []

        for file_name, stream, metadata in stream_iter:
            print(
                f"download idn: {job['idn']}, metadata: {str(metadata)} to {file_name}"
            )
            with (
                s3.open(f"{TARGET_BUCKET_NAME}/{file_name}", "wb") as target_io,
                stream() as source_io,
            ):
                while chunk := source_io.read(DEFAULT_BUFFER_SIZE):
                    target_io.write(chunk)
            job["files"] += [file_name]

        print(s3.info(TARGET_BUCKET_NAME))
        print(s3.ls(TARGET_BUCKET_NAME))

        return job

    @task
    def register_files(job: dict):
        import requests

        file_iris = {
            "https://example.org/file/" + file_name: file_name
            for file_name in job["files"]
        }

        file_update = (
            """
        PREFIX wa: <https://webarchiv.dnb.de/>
        PREFIX wal: <https://d-nb.info/standards/elementset/wal#>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX ex: <https://example.org/>

        INSERT DATA {
            GRAPH wa:data {
        """
            + "\n".join(
                [
                    f'<{file_iri}> a wal:File ; wal:filename "{file_name}"; wal:bucket "{TARGET_BUCKET_NAME}" .'
                    for file_iri, file_name in file_iris.items()
                ]
            )
            + """
            }
            GRAPH wa:prov {
        """
            + "\n".join(
                [
                    f"<{file_iri}> prov:wasGeneratedBy <{job['job_iri']}> ; prov:wasAttributedTo <{PROV_IRI}> ."
                    for file_iri, file_name in file_iris.items()
                ]
            )
            + """
            }
        }
        """
        )

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

    jobs_done(
        register_files.expand(
            job=aras_download.expand(
                job=get_jobs("?idn", "wal:ArasPullJob", {"wal:idn": "?idn"})
            )
        )
    )
    # job_done.expand(job=job_execution.expand(job=get_jobs("?idn", "wal:ArasPullJob", {"wal:idn": "?idn"})))


s3_kubernetes_aras_pull_job()
