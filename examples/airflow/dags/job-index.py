from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task
from boilerplate import get_jobs, jobs_done
from common_context import get_cc

cc, cc_source = get_cc()

## Uses the following connections
# s3_default: s3-connection-secret
# cdx_default: cdx-connection-secret

JOB_TYPE_IRI = "dalajobs:IndexJob"

secret_cdx_default = Secret("env", "SECRET_CDX_DEFAULT", "cdx-connection-secret", "value")
secret_s3_default = Secret("env", "SECRET_S3_DEFAULT", "s3-connection-secret", "value")

warc_collection = "warcs"


@dag(
    schedule=None,  # "@once"
    description="An indexer dag",
    tags=["wacli"],
)
def job_index():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/cdxj-indexer:feature-oci-image-s3fs",
        secrets=[secret_s3_default, secret_cdx_default],
        env_vars={
            "WARC_COLLECTION": warc_collection,
        },
        do_xcom_push=True,
    )
    def index(cc_source: str, job: dict):
        import os
        from io import StringIO

        import requests
        from cdxj_indexer import CDXJIndexer
        from s3fs import S3FileSystem

        exec_locals = {}
        exec(cc_source, locals=exec_locals)  # noqa: S102
        cc = exec_locals["common_context"]

        cdx_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_CDX_DEFAULT"),
            conn_id="cdx_default",
        )
        s3_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_S3_DEFAULT"), conn_id="s3_default"
        )

        cdx_url, _ = cc.http_connection(cdx_conn)
        collection = os.environ.get("WARC_COLLECTION")
        cdx_endpoint = f"{cdx_url}/{collection}"

        cc.set_boto_env(s3_conn, os.environ)
        s3 = S3FileSystem()

        print(
            f"I will now read the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), index it and push the cdx record to outbackcdx. ({job['job_iri']})."
        )

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"

        cdx_stream = StringIO()

        with s3.open(path_in_s3fs, "rb") as source_file:
            CDXJIndexer(None, None).process_one(
                input_=source_file, output=cdx_stream, filename=job["source_filename"]
            )
            print(cdx_stream.getvalue())
            response = requests.post(cdx_endpoint, data=cdx_stream.getvalue())
            response.raise_for_status()

            print(
                f"Successfully uploaded CDX data for {job['source_filename']} ({job['job_iri']})"
            )

        return job

    triple_pattern = """
    ?source_file wal:filename ?source_filename ;
        wal:bucket ?source_bucket .
    """

    jobs_done(
        index.partial(cc_source=cc_source).expand(
            job=get_jobs(
                ["source_file", "source_filename", "source_bucket"],
                JOB_TYPE_IRI,
                {"wal:file": "?source_file"},
                triple_pattern=triple_pattern,
            )
        )
    )


job_index()
