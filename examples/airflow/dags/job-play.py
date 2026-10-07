import os

from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import Connection, dag, task
from common_context import get_cc

# Define secrets - reference k8s secrets by connection ID label
secret_sparql_query_default = Secret(
    "env", "SECRET_SPARQL_QUERY_DEFAULT", "sparql-query-connection-secret", "value"
)

secret_aws_default = Secret("env", "SECRET_S3_DEFAULT", "s3-connection-secret", "value")

cc, cc_source = get_cc()


@dag(
    schedule=None,
    description="A Playground dag demonstrating connections",
    tags=["wacli", "play", "debug"],
)
def playground_play():

    @task()
    def demo_connections():
        # Get connections at module level
        sparql_query_conn = Connection.get("sparql_query_default")
        s3_conn = Connection.get("s3_default")

        # 1. SPARQL Query endpoint (no auth required in this setup)
        response = cc.sparql_query(
            sparql_query_conn, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        )
        print(f"SPARQL Query status: {response.status_code}")

        # 3. S3 endpoint with credentials from connection
        cc.set_boto_env(s3_conn, os.environ)

        import boto3

        s3_client = boto3.client("s3")
        response = s3_client.list_buckets()
        print(
            f"S3 Buckets: {[bucket['Name'] for bucket in response.get('Buckets', [])]}"
        )

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/cdxj-indexer:feature-oci-image-s3fs",
        secrets=[
            secret_sparql_query_default,
            secret_aws_default,
        ],
    )
    def demo_kubernetes_task(cc_source: str):
        import os

        import botocore
        import s3fs

        print(cc_source)

        exec_locals = {}
        exec(cc_source, locals=exec_locals)  # noqa: S102
        cc = exec_locals["common_context"]

        sparql_query_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_SPARQL_QUERY_DEFAULT"),
            conn_id="sparql_query_default",
        )
        s3_conn = cc.Connection.from_json(
            value=os.getenv("SECRET_S3_DEFAULT"), conn_id="s3_default"
        )

        # 1. SPARQL Query endpoint (no auth required in this setup)
        response = cc.sparql_query(
            sparql_query_conn, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        )
        print(f"SPARQL Query status: {response.status_code}")

        # 3. S3 endpoint with credentials from connection
        cc.set_boto_env(s3_conn, os.environ)

        s3fs.S3FileSystem()
        session = botocore.session.get_session()
        s3_client = session.create_client("s3")
        response = s3_client.list_buckets()
        print(
            f"S3 Buckets: {[bucket['Name'] for bucket in response.get('Buckets', [])]}"
        )

    demo_connections()
    demo_kubernetes_task(cc_source)


playground_play()
