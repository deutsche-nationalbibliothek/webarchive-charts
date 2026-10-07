from inspect import getsource
from textwrap import dedent

"""
This common context is a mechanism to share connections among python tasks and kubernetes tasks.

Usage example:

```python
from airflow.sdk import Connection, dag, task
from common_context import get_cc

secret_sparql_query_default = Secret(
    "env", "SECRET_SPARQL_QUERY_DEFAULT", "sparql-query-connection-secret", "value"
)

secret_aws_default = Secret("env", "SECRET_S3_DEFAULT", "s3-connection-secret", "value")

cc, cc_source = get_cc()

@dag(…)
def my_dag():

    @task
    def my_python_task():
        sparql_query_conn = Connection.get("sparql_query_default")
        s3_conn = Connection.get("s3_default")

        # Setup and use SPARQL
        response = cc.sparql_query(
            sparql_query_conn, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        )
        print(f"SPARQL Query status: {response.status_code}")

        # Setup S3 endpoint
        cc.set_boto_env(s3_conn, os.environ)

        …


    @task.kubernetes(
        image="…",
        secrets=[
            secret_sparql_query_default,
            secret_aws_default,
        ],
    )
    def my_kubernetes_task(cc_source: str):
        import os

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

        # Setup and use SPARQL
        response = cc.sparql_query(
            sparql_query_conn, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        )
        print(f"SPARQL Query status: {response.status_code}")

        # Setup S3 endpoint
        cc.set_boto_env(s3_conn, os.environ)

    my_python_task()
    my_kubernetes_task(cc_source)


my_dag()

```
"""

class common_context:
    """This is a class to wrap a common context of code to transport it into the KubernetesPodOperator"""

    from dataclasses import dataclass

    @dataclass
    class Connection:
        """Mocking an airflow.sdk.Connection object to be compatble with it in kubernetes code.

        Caution: secrets are not masked
        """

        conn_id: str | None = None
        host: str | None = None
        port: str | None = None
        schema: str | None = None
        login: str | None = None
        password: str | None = None
        extra: dict | None = None

        @property
        def extra_dejson(self) -> dict:
            """returns the extra property which is already deserialized json."""

            return self.extra

        @classmethod
        def from_json(cls, value: str, conn_id=None):
            """Deserialize a secret from json"""
            import json

            config = json.loads(value)
            if config:
                return cls(
                    conn_id=conn_id,
                    host=config.get("host"),
                    port=config.get("port"),
                    schema=config.get("schema"),
                    login=config.get("login"),
                    password=config.get("password"),
                    extra=config.get("extra"),
                )
            return cls(conn_id=conn_id, extra={})

    @classmethod
    def http_connection(cls, conn) -> tuple[str, tuple[str, str] | None]:
        """Get a tuple of http endpoint URL (e.g. sparql endpoint) and auth tuple from a connection object to use it with requests"""
        url_scheme = conn.extra_dejson.get("url_scheme") or "http"
        endpoint_url = f"{url_scheme}://{conn.host}:{conn.port}/{conn.schema}"
        auth_tuple = None
        if conn.login:
            auth_tuple = (
                conn.login,
                conn.password or "",
            )
        return endpoint_url, auth_tuple

    @classmethod
    def set_boto_env(cls, conn, env):
        """Set the environment variables for a boto aws connection."""
        aws_endpoint_url_s3 = conn.extra_dejson.get("endpoint_url")
        aws_default_region = conn.extra_dejson.get("region_name")

        env["AWS_ENDPOINT_URL_S3"] = aws_endpoint_url_s3 or ""
        env["AWS_DEFAULT_REGION"] = aws_default_region or ""
        env["AWS_ACCESS_KEY_ID"] = conn.login or ""
        env["AWS_SECRET_ACCESS_KEY"] = conn.password or ""


    @classmethod
    def sparql_query(
        cls,
        conn,
        query: str,
        content_type: str = "application/sparql-query",
        backend_library=None,
    ):
        """Query a sparql endpoint defined by a Connection object.

        Requires non sandard python requests or rdflib module to be available.
        """

        endpoint_url, auth_tuple = cls.http_connection(conn)

        if backend_library == "requests":
            import requests
        elif backend_library == "rdflib":
            import rdflib

        try:
            import requests

            backend_library = "requests"
        except ImportError:
            import rdflib

            backend_library = "rdflib"

        if backend_library == "requests":
            response = requests.post(
                endpoint_url,
                auth=auth_tuple,
                data=query,
                headers={"Content-Type": content_type},
            )
            return response
        elif backend_library == "rdflib":
            raise Exception("The rdflib backend needs to be implemented")

def get_cc():
    return common_context, dedent(getsource(common_context))