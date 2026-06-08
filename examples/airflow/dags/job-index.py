from airflow.sdk import dag, task
from airflow.providers.cncf.kubernetes.secret import Secret
from boilerplate import get_jobs, jobs_done

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


@dag(
    schedule=None,  # "@once"
    description="An indexer dag",
    tags=["wacli"],
)
def job_index():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/warcio:feature-oci-image-s3",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": "http://webarchive-versitygw:7070",
            "AWS_DEFAULT_REGION": "eu-central-1",
            "OUTBACK_CDX_URL": "http://outbackcdx-service:8080/outbackcdx/",
            "WARC_COLLECTION": "warcs",
        },
        do_xcom_push=True,
    )
    def index(job: dict):
        from warcio.indexer import Indexer
        from s3fs import S3FileSystem
        import tempfile
        import os
        import requests

        DEFAULT_CDX_FILEDS = "offset,warc-type,warc-target-uri"
        cdx_url = os.environ.get("OUTBACK_CDX_URL")
        collection = os.environ.get("WARC_COLLECTION")

        cdx_endpoint = f"{cdx_url}{collection}"

        s3 = S3FileSystem()

        print(
            f"I will now download the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), index it and push the cdx record to outbackcdx. ({job['job_iri']})."
        )

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"


        # Create a temporary file using Python's tempfile module
        # with tempfile.NamedTemporaryFile(mode='w', suffix='.cdx') as tmp_cdx_file:
        with tempfile.TemporaryFile(mode="w+", suffix=".cdx") as tmp_cdx_file, s3.open(path_in_s3fs, "rb") as source_file:
            Indexer(DEFAULT_CDX_FILEDS, [], None).process_one(source_file, output=tmp_cdx_file, filename=path_in_s3fs)

            tmp_cdx_file.seek(0)
            cdx_content = tmp_cdx_file.read()
            print(cdx_content)
            response = requests.post(cdx_endpoint, data=cdx_content)
            response.raise_for_status()

            print(f"Successfully uploaded CDX data for {job['source_filename']}")

        return job

    triple_pattern = """
    ?source_file wal:filename ?source_filename ;
        wal:bucket ?source_bucket .
    """

    jobs_done(
        index.expand(
            job=get_jobs(
                ["source_file", "source_filename", "source_bucket"],
                "wal:IndexJob",
                {"wal:file": "?source_file"},
                triple_pattern=triple_pattern,
            )
        )
    )


job_index()
