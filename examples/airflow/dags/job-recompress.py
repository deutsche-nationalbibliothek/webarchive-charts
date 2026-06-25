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

PROV_IRI = "https://webarchiv.dnb.de/workflow/recompress/v1"


@dag(
    schedule=None,  # "@once"
    description="A recompress dag",
    tags=["wacli"],
)
def s3_kubernetes_recompress_job():

    def job_failed(context):
        task_instance = context.task_instance
        job_iri = task_instance.xcom_pull(key="job")
        print(f"job {job_iri} failed")
        print(context)
        print(context.get("exception").args)
        print(f"job_iri: {job_iri}")
        jobs_failed([{"job_iri": job_iri}])

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/warcio:feature-oci-image-s3",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": "http://webarchive-versitygw:7070",
            "AWS_DEFAULT_REGION": "eu-central-1",
        },
        do_xcom_push=True,
        on_failure_callback=job_failed,
    )
    def recompress(job: dict):
        from warcio.recompressor import Recompressor
        from s3fs import S3FileSystem

        TARGET_BUCKET_NAME = "webarchive"

        s3 = S3FileSystem()

        try:
            s3.mkdir(TARGET_BUCKET_NAME, create_parents=True)
        except FileExistsError:
            pass

        print(
            f"I will now download the file {job['source_file']} (bucket: {job['source_bucket']}, filename: {job['source_filename']}), recompress it and upload it to the s3 bucket {TARGET_BUCKET_NAME}. ({job['job_iri']})."
        )

        # Download the file according to the graphs file spec
        # recompress it and upload it

        path_in_s3fs = f"s3://{job['source_bucket']}/{job['source_filename']}"
        path_out_s3fs = f"s3://{TARGET_BUCKET_NAME}/{job['source_filename']}"

        print("start recompression")
        Recompressor(path_in_s3fs, path_out_s3fs).recompress()
        print("end recompression")

        print(s3.info(TARGET_BUCKET_NAME))
        print(s3.ls(TARGET_BUCKET_NAME))

        job["files"] = [job['source_filename']]

        return job


    @task(trigger_rule="all_done")
    def register_files(job: dict):
        import requests

        TARGET_BUCKET_NAME = "webarchive"

        file_iris = {
            "https://example.org/file/" + TARGET_BUCKET_NAME + "/" + file_name: file_name
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
                    f'<{file_iri}> a wal:File ; wal:filename "{file_name}"; wal:bucket "{TARGET_BUCKET_NAME}" ; wal:fileStatus ex:clean.'
                    for file_iri, file_name in file_iris.items()
                ]
            )
            + """
            }
            GRAPH wa:prov {
        """
            + "\n".join(
                [
                    f"<{file_iri}> prov:wasGeneratedBy <{job['job_iri']}> ; prov:wasAttributedTo <{PROV_IRI}>; prov:wasDerivedFrom <{file_iri}> ."
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

    triple_pattern = """
    ?source_file wal:filename ?source_filename ;
        wal:bucket ?source_bucket .
    """

    jobs_done(
        register_files.expand(
            job=recompress.expand(
                job=get_jobs(
                    ["source_file", "source_filename", "source_bucket"],
                    "wal:RecompressJob",
                    {"wal:file": "?source_file"},
                    triple_pattern=triple_pattern,
                )
            )
        )
    )
    # job_done.expand(job=job_execution.expand(job=get_jobs("?idn", "wal:ArasPullJob", {"wal:idn": "?idn"})))


s3_kubernetes_recompress_job()
