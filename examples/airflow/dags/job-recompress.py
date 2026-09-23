from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task
from boilerplate import (
    FILE_BASE_IRI,
    PREFIXES,
    PROV_BASE_IRI,
    get_jobs,
    job_failed,
    jobs_done,
)

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

PROV_IRI = f"<{PROV_BASE_IRI}recompress:v1>"
JOB_TYPE_IRI = "dalajobs:RecompressJob"


@dag(
    schedule=None,  # "@once"
    description="A recompress dag",
    tags=["wacli"],
)
def s3_kubernetes_recompress_job():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/warcio:feature-oci-image-s3",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": aws_endpoint_url_s3,
            "AWS_DEFAULT_REGION": aws_default_region,
        },
        do_xcom_push=True,
        on_failure_callback=job_failed,
        pod_template_dict={
            "spec": {
                "containers": [
                    {
                        "name": "base",
                        "resources": {
                            "limits": {"cpu": "500m", "memory": "1Gi"},
                            "requests": {"cpu": "500m", "memory": "1Gi"},
                        },
                    }
                ]
            }
        },
    )
    def recompress(job: dict):
        import gzip

        from s3fs import S3FileSystem
        from warcio.archiveiterator import ArchiveIterator
        from warcio.recompressor import Recompressor
        from warcio.warcwriter import WARCWriter

        TARGET_BUCKET_NAME = "webarchive"

        s3 = S3FileSystem(config_kwargs={"retries": {"mode": "adaptive"}})
        # How could a socket.gaierror be handled propperly

        try:
            s3.mkdir(TARGET_BUCKET_NAME, create_parents=True)
        except FileExistsError:
            pass

        print(
            f"""Executing Job: <{job["job_iri"]}>

                I will do the following:
                1. download the file {job["source_file"]} (bucket: {job["source_bucket"]}, filename: {job["source_filename"]})
                2a. recompress it and
                2b. in the same run upload it to the s3 bucket {TARGET_BUCKET_NAME}."""
        )

        # Download the file according to the graphs file spec
        # recompress it and upload it

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"
        path_out_s3fs = f"s3://{TARGET_BUCKET_NAME}/{job['source_filename']}"

        print("start recompression")

        with s3.open(path_in_s3fs, "rb") as stream_in:
            # TODO check if this works
            # count = 0
            # decompressed_stream_in = gzip.GzipFile(fileobj=stream_in)
            # with s3.open(path_out_s3fs, "rb") as stream_out:
            #     writer = WARCWriter(filebuf=stream_out, gzip=True)

            #     for record in ArchiveIterator(decompressed_stream_in,
            #                                 no_record_parse=False,
            #                                 arc2warc=True,
            #                                 verify_http=False):

            #         writer.write_record(record)
            #         count += 1

            # print(f"{count} records read and recompressed")

            Recompressor(None, None).decompress_and_recompress(stream_in, path_out_s3fs)
        # Recompressor(path_in_s3fs, path_out_s3fs).recompress()
        print("end recompression")

        print(s3.info(TARGET_BUCKET_NAME))
        print(s3.ls(TARGET_BUCKET_NAME))
        print(f"wrote recompressed file directly to {path_out_s3fs}")

        job["files"] = [job["source_filename"]]

        return job

    @task(trigger_rule="all_done")
    def register_files(job: dict):
        import requests

        TARGET_BUCKET_NAME = "webarchive"

        file_iris = {
            FILE_BASE_IRI + TARGET_BUCKET_NAME + "/" + file_name: file_name
            for file_name in job["files"]
        }

        file_update = (
            PREFIXES
            + """
        INSERT DATA {
            GRAPH wag:data {
        """
            + "\n".join(
                [
                    f'<{file_iri}> a wal:File ; wal:filename "{file_name}"; wal:bucket "{TARGET_BUCKET_NAME}" ; wal:fileStatus filestatus:clean.'
                    for file_iri, file_name in file_iris.items()
                ]
            )
            + """
            }
            GRAPH wag:prov {
        """
            + "\n".join(
                [
                    f"<{file_iri}> prov:wasGeneratedBy <{job['job_iri']}> ; prov:wasAttributedTo {PROV_IRI}; prov:wasDerivedFrom <{file_iri}> ."
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
            auth=sparql_update_auth_tuple,
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
            job=recompress.expand(
                job=get_jobs(
                    ["source_file", "source_filename", "source_bucket"],
                    JOB_TYPE_IRI,
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )


s3_kubernetes_recompress_job()
