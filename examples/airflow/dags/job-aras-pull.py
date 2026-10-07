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
from common_context import get_cc

PROV_IRI = f"<{PROV_BASE_IRI}oGet>"
JOB_TYPE_IRI = "dalajobs:ArasPullJob"

## Uses the followin connections
# sparql_update_default: sparql-update-connection-secret
# s3_default: s3-connection-secret
# aras_default: aras-connection-secret

# Define secrets - reference k8s secrets by connection ID label
secret_aras_default = Secret(
    "env", "SECRET_ARAS_DEFAULT", "aras-connection-secret", "value"
)

secret_s3_default = Secret("env", "SECRET_S3_DEFAULT", "s3-connection-secret", "value")

cc, cc_source = get_cc()

target_bucket_name = "waingest"
aras_repo = "warc"


@dag(
    schedule=None,  # "@once"
    description="A k8n dag",
    tags=["wacli"],
)
def s3_kubernetes_aras_pull_job():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/aras-py:main-s3",
        secrets=[secret_aras_default, secret_s3_default],
        env_vars={
            "TARGET_BUCKET_NAME": target_bucket_name,
            "ARAS_REPO": aras_repo,
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
    def aras_download(cc_source: str, job: dict):
        import os
        from shutil import copyfileobj

        import s3fs
        from aras_py.run import get_stream

        exec_locals = {}
        exec(cc_source, locals=exec_locals)  # noqa: S102
        cc = exec_locals["common_context"]

        aras_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_ARAS_DEFAULT"),
            conn_id="aras_default",
        )
        s3_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_S3_DEFAULT"), conn_id="s3_default"
        )

        aras_rest_base, _ = cc.http_connection(aras_conn)
        cc.set_boto_env(s3_conn, os.environ)

        target_bucket_name = os.environ["TARGET_BUCKET_NAME"]
        aras_repo = os.environ["ARAS_REPO"]

        s3 = s3fs.S3FileSystem()

        try:
            s3.mkdir(target_bucket_name, create_parents=True)
        except FileExistsError:
            pass

        print(
            f"I will now download the files for {job['idn']} and upload them to the s3 bucket {target_bucket_name}. ({job['job_iri']})."
        )

        stream_iter = get_stream(aras_rest_base, aras_repo, job["idn"])

        job["files"] = []

        for file_name, stream, metadata in stream_iter:
            print(
                f"download idn: {job['idn']}, metadata: {str(metadata)} to {file_name}"
            )
            with (
                s3.open(f"{target_bucket_name}/{file_name}", "wb") as target_io,
                stream() as source_io,
            ):
                copyfileobj(source_io, target_io)
            job["files"] += [file_name]

        print(s3.info(target_bucket_name))
        print(s3.ls(target_bucket_name))

        return job

    @task(trigger_rule="all_done")
    def register_files(job: dict):

        sparql_update_conn = Connection.get("sparql_update_default")

        file_iris = {FILE_BASE_IRI + file_name: file_name for file_name in job["files"]}

        file_update = (
            PREFIXES
            + """

        INSERT DATA {
            GRAPH wag:data {
        """
            + "\n".join(
                [
                    f'<{file_iri}> a wal:File ; wal:filename "{file_name}"; wal:bucket "{target_bucket_name}" .'
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

        r = cc.sparql_update(sparql_update_conn, file_update)

        print(r)
        print(r.text)

        r.raise_for_status()
        return job

    jobs_done(
        register_files.expand(
            job=aras_download.partial(cc_source=cc_source).expand(
                job=get_jobs(["idn"], JOB_TYPE_IRI, {"wal:idn": "?idn"})
            )
        )
    )
    # job_done.expand(job=job_execution.expand(job=get_jobs("?idn", "wal:ArasPullJob", {"wal:idn": "?idn"})))


s3_kubernetes_aras_pull_job()
