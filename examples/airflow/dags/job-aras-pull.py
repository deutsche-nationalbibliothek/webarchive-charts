from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task
from boilerplate import (
    FILE_BASE_IRI,
    PREFIXES,
    PROV_BASE_IRI,
    get_jobs,
    jobs_done,
    jobs_failed,
)

PROV_IRI = f"<{PROV_BASE_IRI}oGet>"
JOB_TYPE_IRI = "dalajobs:ArasPullJob"

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
    description="A k8n dag",
    tags=["wacli"],
)
def s3_kubernetes_aras_pull_job():

    def job_failed(context):
        task_instance = context.task_instance
        job_iri = task_instance.xcom_pull(key="job")
        print(f"job {job_iri} failed")
        print(context)
        print(context.get("exception").args)
        print(f"job_iri: {job_iri}")
        jobs_failed([{"job_iri": job_iri}])

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/aras-py:main-s3",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        env_vars={
            "AWS_ENDPOINT_URL_S3": "http://webarchive-versitygw:7070",
            "AWS_DEFAULT_REGION": "eu-central-1",
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
                    # The xcom-sidecar resources are retrieved via sidecar_container_resources=self.hook.get_xcom_sidecar_container_resources()
                    # https://github.com/apache/airflow/blob/1b246e8c1eb9b077b180df5b8f0fd7b10e83b0ab/providers/cncf/kubernetes/src/airflow/providers/cncf/kubernetes/operators/pod.py#L1665
                    #  {
                    #     "name": "airflow-xcom-sidecar",
                    #     "resources": {
                    #         "limits": {"cpu": "50m", "memory": "128Mi"},
                    #         "requests": {"cpu": "50m", "memory": "128Mi"},
                    #     },
                    # },
                ]
            }
        },
    )
    def aras_download(job: dict):
        import s3fs
        from aras_py.run import get_stream
        from shutil import copyfileobj

        # load with aras-py and write to s3
        TARGET_BUCKET_NAME = "waingest"

        ARAS_REST_BASE = "http://mockils-service:8080/"
        ARAS_REPO = "warc"

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
                copyfileobj(source_io, target_io)
            job["files"] += [file_name]

        print(s3.info(TARGET_BUCKET_NAME))
        print(s3.ls(TARGET_BUCKET_NAME))

        return job

    @task(trigger_rule="all_done")
    def register_files(job: dict):
        import requests
        TARGET_BUCKET_NAME = "waingest"

        file_iris = {
            FILE_BASE_IRI + file_name: file_name
            for file_name in job["files"]
        }

        file_update = (
            PREFIXES + """

        INSERT DATA {
            GRAPH wag:data {
        """
            + "\n".join(
                [
                    f'<{file_iri}> a wal:File ; wal:filename "{file_name}"; wal:bucket "{TARGET_BUCKET_NAME}" .'
                    for file_iri, file_name in file_iris.items()
                ]
            )
            + """
            }
            GRAPH wag:prov {
        """
            + "\n".join(
                [
                    f"<{file_iri}> prov:wasGeneratedBy <{job['job_iri']}> ; prov:wasAttributedTo {PROV_IRI} ."
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
                job=get_jobs(["idn"], JOB_TYPE_IRI, {"wal:idn": "?idn"})
            )
        )
    )
    # job_done.expand(job=job_execution.expand(job=get_jobs("?idn", "wal:ArasPullJob", {"wal:idn": "?idn"})))


s3_kubernetes_aras_pull_job()
