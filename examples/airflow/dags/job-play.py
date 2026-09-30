import os

from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import Connection, dag, task

# Define secrets - reference k8s secrets by connection ID label
secret_sparql_query_default = Secret(
    "env", "SECRET_SPARQL_QUERY_DEFAULT", "fuseki-query-secret", "value"
)

secret_aws_default = Secret("env", "SECRET_AWS_DEFAULT", "s3-secret", "value")


@dag(
    schedule=None,
    description="A Playground dag demonstrating connections",
    tags=["wacli", "play", "debug"],
)
def playground_play():

    @task()
    def demo_connections():
        import json

        import requests

        # Get connections at module level
        sparql_query_conn = Connection.get("sparql_query_default")
        aws_conn = Connection.get("aws_default")

        # Build URLs from connection objects
        sparql_query_url = f"http://{sparql_query_conn.host}:{sparql_query_conn.port}/{sparql_query_conn.schema}"
        sparql_query_auth_tuple = None
        if sparql_query_conn.login and sparql_query_conn.password:
            sparql_query_auth_tuple = (
                sparql_query_conn.login,
                sparql_query_conn.password,
            )
            print(f"Using auth: {sparql_query_auth_tuple[0]} for SPARQL")
        else:
            print("No auth configured for SPARQL update")

        aws_conn_extra = json.loads(aws_conn.extra)

        aws_endpoint_url_s3 = aws_conn_extra.get("endpoint_url")
        aws_default_region = aws_conn_extra.get("region_name")

        os.environ["AWS_ENDPOINT_URL_S3"] = aws_endpoint_url_s3 or ""
        os.environ["AWS_DEFAULT_REGION"] = aws_default_region or ""
        os.environ["AWS_ACCESS_KEY_ID"] = aws_conn.login or ""
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_conn.password or ""

        # 1. SPARQL Query endpoint (no auth required in this setup)
        print(f"Query URL: {sparql_query_url}")
        response = requests.post(
            sparql_query_url,
            auth=sparql_query_auth_tuple,
            data="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1",
            headers={"Content-Type": "application/sparql-query"},
        )
        print(f"SPARQL Query status: {response.status_code}")

        # 3. S3 endpoint with credentials from connection
        print(f"AWS Endpoint: {os.getenv('AWS_ENDPOINT_URL_S3')}")
        print(f"AWS Region: {os.getenv('AWS_DEFAULT_REGION')}")
        print(f"Access Key (login): {os.getenv('AWS_ACCESS_KEY_ID')}")
        print(f"Secret Key (password): {os.getenv('AWS_SECRET_ACCESS_KEY')}")

        import boto3

        s3_client = boto3.client("s3")
        response = s3_client.list_buckets()
        print(f"S3 Buckets: {[bucket['Name'] for bucket in response.get('Buckets', [])]}")

    @task.kubernetes(
        image="ghcr.io/deutsche-nationalbibliothek/cdxj-indexer:feature-oci-image-s3fs",
        secrets=[
            secret_sparql_query_default,
            secret_aws_default,
        ],
        env_vars={
            # "AWS_ENDPOINT_URL_S3": aws_endpoint_url_s3 or "",
            # "AWS_DEFAULT_REGION": aws_default_region or "",
            # "SPARQL_QUERY_URL": sparql_query_url or "",
        },
    )
    def demo_kubernetes_task():
        import json
        import os
        from dataclasses import dataclass

        import requests
        import s3fs

        @dataclass
        class Connection:
            host: str | None = None
            port: str | None = None
            schema: str | None = None
            login: str | None = None
            password: str | None = None
            extra: dict | None = None

        def parse_connection(secret):
            config = json.loads(secret)
            if config:
                return Connection(
                    host=config.get("host"),
                    port=config.get("port"),
                    schema=config.get("schema"),
                    login=config.get("login"),
                    password=config.get("password"),
                    extra=config.get("extra"),
                )
            return Connection(extra={})

        sparql_query_conn = parse_connection(os.getenv("SECRET_SPARQL_QUERY_DEFAULT"))
        aws_conn = parse_connection(os.getenv("SECRET_AWS_DEFAULT"))

        # Build URLs from connection objects
        sparql_query_url = f"http://{sparql_query_conn.host}:{sparql_query_conn.port}/{sparql_query_conn.schema}"
        sparql_query_auth_tuple = None
        if sparql_query_conn.login and sparql_query_conn.password:
            sparql_query_auth_tuple = (
                sparql_query_conn.login,
                sparql_query_conn.password,
            )
            print(f"Using auth: {sparql_query_auth_tuple[0]}")
        else:
            print("No auth configured for SPARQL update")

        aws_endpoint_url_s3 = aws_conn.extra.get("endpoint_url")
        aws_default_region = aws_conn.extra.get("region_name")

        os.environ["AWS_ENDPOINT_URL_S3"] = aws_endpoint_url_s3 or ""
        os.environ["AWS_DEFAULT_REGION"] = aws_default_region or ""
        os.environ["AWS_ACCESS_KEY_ID"] = aws_conn.login or ""
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_conn.password or ""

        def parse_credentials(secret):
            config = json.loads(secret)
            if config:
                return (config.get("login"), config.get("password"))
            return (None, None)

        sparql_query_auth_tuple = parse_credentials(
            os.getenv("SECRET_SPARQL_QUERY_DEFAULT")
        )
        aws_auth_tuple = parse_credentials(os.getenv("SECRET_AWS_DEFAULT"))

        os.environ["AWS_ENDPOINT_URL_S3"] = aws_endpoint_url_s3 or ""
        os.environ["AWS_DEFAULT_REGION"] = aws_default_region or ""
        os.environ["AWS_ACCESS_KEY_ID"] = aws_auth_tuple[0] or ""
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_auth_tuple[1] or ""

        # Disable for now since we are using adapter code
        #
        # sparql_query_url = os.getenv("SPARQL_QUERY_URL")
        response = requests.post(
            sparql_query_url,
            auth=sparql_query_auth_tuple,
            data="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1",
            headers={"Content-Type": "application/sparql-query"},
        )
        print(f"SPARQL Query status: {response.status_code}")


        import botocore

        session = botocore.session.get_session()
        s3_client = session.create_client("s3")
        response = s3_client.list_buckets()
        print(f"S3 Buckets: {[bucket['Name'] for bucket in response.get('Buckets', [])]}")


    demo_connections()
    demo_kubernetes_task()


playground_play()
