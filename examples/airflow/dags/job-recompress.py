from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import Connection, dag, task
from boilerplate import (
    FILE_BASE_IRI,
    PREFIXES,
    PROV_BASE_IRI,
    get_jobs,
    job_failed,
    jobs_done,
)
from boilerplate import recompress_job_asset as job_asset
from common_context import get_cc

cc, cc_source = get_cc()

## Uses the following connections
# sparql_update_default: sparql-update-connection-secret
# s3_default: s3-connection-secret

JOB_IRI_LOCAL_PART = "RecompressJob"

PROV_IRI = f"<{PROV_BASE_IRI}recompress:v1>"
JOB_TYPE_QNAME = "dalajobs:" + JOB_IRI_LOCAL_PART

secret_s3_default = Secret("env", "SECRET_S3_DEFAULT", "s3-connection-secret", "value")

target_bucket_name = "webarchive"

@dag(
    schedule=job_asset,  # "@once"
    description="A recompress dag",
    tags=["wacli"],
)
def s3_kubernetes_recompress_job():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/warcio:feature-oci-image-s3",
        secrets=[secret_s3_default],
        env_vars={
            "TARGET_BUCKET_NAME": target_bucket_name,
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
    def recompress(cc_source: str, job: dict):
        import gzip
        import os

        from s3fs import S3FileSystem
        from warcio.archiveiterator import ArchiveIterator
        from warcio.recompressor import Recompressor
        from warcio.warcwriter import WARCWriter

        exec_locals = {}
        exec(cc_source, locals=exec_locals)  # noqa: S102
        cc = exec_locals["common_context"]

        s3_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_S3_DEFAULT"), conn_id="s3_default"
        )

        cc.set_boto_env(s3_conn, os.environ)

        target_bucket_name = os.environ["TARGET_BUCKET_NAME"]

        s3 = S3FileSystem(
            client_kwargs={
                "region_name": os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
            },
        )

        try:
            s3.mkdir(target_bucket_name, create_parents=True)
        except FileExistsError:
            pass

        print(
            f"""Executing Job: <{job["job_iri"]}>

                I will do the following:
                1. download the file {job["source_file"]} (bucket: {job["source_bucket"]}, filename: {job["source_filename"]})
                2a. recompress it and
                2b. in the same run upload it to the s3 bucket {target_bucket_name}."""
        )

        # Download the file according to the graphs file spec
        # recompress it and upload it

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"
        path_out_s3fs = f"s3://{target_bucket_name}/{job['source_filename']}"

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

        print(s3.info(target_bucket_name))
        print(s3.ls(target_bucket_name))
        print(f"wrote recompressed file directly to {path_out_s3fs}")

        job["files"] = [job["source_filename"]]

        return job

    @task(trigger_rule="all_done")
    def register_files(job: dict):
        sparql_update_conn = Connection.get("sparql_update_default")

        file_iris = {
            FILE_BASE_IRI + target_bucket_name + "/" + file_name: file_name
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
                    f'<{file_iri}> a wal:File ; wal:filename "{file_name}"; wal:bucket "{target_bucket_name}" ; wal:fileStatus filestatus:clean.'
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
            job=recompress.partial(cc_source=cc_source).expand(
                job=get_jobs(
                    ["source_file", "source_filename", "source_bucket"],
                    JOB_TYPE_QNAME,
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )


s3_kubernetes_recompress_job()
