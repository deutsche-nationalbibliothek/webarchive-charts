from airflow.sdk import dag, task
from airflow.providers.cncf.kubernetes.secret import Secret

secret_env_access_key = Secret(
    "env", "AWS_ACCESS_KEY_ID", "airflow-versitygw-credentials", "rootAccessKeyId"
)
secret_env_secret_access_key = Secret(
    "env",
    "AWS_SECRET_ACCESS_KEY",
    "airflow-versitygw-credentials",
    "rootSecretAccessKey",
)

sparql_update_endpoint = (
    "http://airflow-fuseki.default.svc.cluster.local:3030/ds/update"
)


@dag(
    schedule=None,  # "@once"
    description="Creates jobs",
    tags=["wacli"],
)
def job_creator():

    @task
    def create_jobs():
        import requests

        job_update = """
        PREFIX wa: <https://webarchiv.dnb.de/>
        PREFIX wal: <https://d-nb.info/standards/elementset/wal#>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX ex: <https://example.org/>

        INSERT {
            GRAPH wa:jobs {
                ?job wal:Job, wal:RecompressJob ;
                    wal:file ?file .
            }
        } WHERE {
            ?file a wal:File ;
                prov:wasAttributedTo <https://example.org/oia-duesseldorf/oGet> .

            FILTER NOT EXISTS {
                ?recompressedFile a wal:File ;
                    wal:fileStatus ex:clean ;
                    prov:wasDerivedFrom ?file .
            }

            FILTER NOT EXISTS {
                ?recompressJob a wal:Job, wal:RecompressJob ;
                    wal:file ?file .
            }

            BIND (UUID() as ?job)
        }
        """

        r = requests.post(
            sparql_update_endpoint,
            auth=("admin", "admin"),
            headers={
                "Accept": "application/sparql-results+json,*/*;q=0.9",
                "Content-Type": "application/sparql-update",
            },
            data=job_update,
        )

        print(r)
        print(r.text)

        r.raise_for_status()

        create_jobs()


job_creator()
