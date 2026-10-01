from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task

secret_env_access_key = Secret(
    "env", "AWS_ACCESS_KEY_ID", "webarchive-versitygw-credentials", "rootAccessKeyId"
)
secret_env_secret_access_key = Secret(
    "env",
    "AWS_SECRET_ACCESS_KEY",
    "webarchive-versitygw-credentials",
    "rootSecretAccessKey",
)


@dag(
    schedule=None,  # "@once"
    description="A Playground dag",
    tags=["wacli", "play", "debug"],
)
def playground_play():

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/cdxj-indexer:feature-oci-image-s3fs",
        secrets=[secret_env_access_key, secret_env_secret_access_key],
        do_xcom_push=True,
    )
    def play_kube(job: dict):
        import os
        print(os.environ.get("AWS_ACCESS_KEY_ID"))
        print(os.environ.get("AWS_SECRET_ACCESS_KEY"))

    @task()
    def play_raw():
        print(secret_env_access_key)
        print(secret_env_access_key.items)
        print(secret_env_access_key.secret)
        print(secret_env_access_key.to_env_secret())

    play_kube(play_raw())


playground_play()
