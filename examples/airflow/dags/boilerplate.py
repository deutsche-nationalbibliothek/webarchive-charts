from textwrap import dedent

import requests
from airflow.sdk import task
from requests.exceptions import JSONDecodeError

sparql_query_endpoint = "http://webarchive-fuseki:3030/ds/query"
sparql_update_endpoint = "http://webarchive-fuseki:3030/ds/update"

BASE_IRI = "https://d-nb.info/"

WEBARCHIVE_BASE_IRI = BASE_IRI + "webarchive/"
GRAPH_BASE_IRI = WEBARCHIVE_BASE_IRI + "graphs/"
FILE_BASE_IRI = WEBARCHIVE_BASE_IRI + "files/"

PROV_BASE_IRI = BASE_IRI + "provenance/webarchive/plan#"

WAL_NAMESPACE = BASE_IRI + "standards/elementset/wal#"
FILESTATUS_NAMESPACE = BASE_IRI + "standards/vocab/filestatus#"
DALAJOBS_NAMESPACE = BASE_IRI + "standards/vocab/datalakejobs#"

PREFIXES = dedent(f"""
    PREFIX wag: <{GRAPH_BASE_IRI}>
    PREFIX wal: <{WAL_NAMESPACE}>
    PREFIX filestatus: <{FILESTATUS_NAMESPACE}>
    PREFIX dalajobs: <{DALAJOBS_NAMESPACE}>
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX wapplan: <{PROV_BASE_IRI}>
    """)

PREFIXES + """
filestatus:clean
filestatus:indexed
filestatus:metadata_extracted
"""

PREFIXES + """
wapplan:oGet
"""

PREFIXES + """
wal:fileStatus
wal:File
wal:Job
wal:bucket
wal:filename
wal:idn
"""

PREFIXES + """
dalajobs:RecompressJob
dalajobs:IndexJob
dalajobs:MetadataExtractJob
dalajobs:ArasPullJob
"""

@task
def get_jobs(
    projection: str = [],
    rdf_type: str = "wal:Job",
    properties: dict = {},
    triple_pattern: str = "",
    limit: int = 10,
):

    job_query = (
        PREFIXES + f"""
    SELECT ?job {" ".join(f"?{var}" for var in projection)} {{
        GRAPH wag:jobs {{
            ?job a {rdf_type} ;
    """
        + ";\n".join([f"{prop[0]} {prop[1]}" for prop in properties.items()])
        + " . "
        + """
            FILTER NOT EXISTS { ?job wal:status ?status . VALUES ?status { wal:done wal:failed wal:skip } }
        }"""
        + triple_pattern
        + f"""
    }}
    limit {limit}
    """
    )

    print(job_query)

    r = requests.post(
        sparql_query_endpoint,
        auth=("admin", "admin"),
        headers={
            "Accept": "application/sparql-results+json,*/*;q=0.9",
            "Content-Type": "application/sparql-query",
        },
        data=job_query,
    )
    try:
        return [
            {
                "job_iri": job["job"]["value"],
                **{var: job[var]["value"] for var in projection},
            }
            for job in r.json()["results"]["bindings"]
        ]
    except JSONDecodeError:
        print("Error")
        print(job_query)
        print(r.text)
        pass


@task
def job_done(job: dict = None):
    return _jobs_done([job])


@task(trigger_rule="all_done")
def jobs_done(jobs: list[dict] = None):
    return _jobs_done(jobs)


def _jobs_done(jobs: list[dict]):

    job_update = dedent(
        PREFIXES + """
        INSERT DATA {
            GRAPH wag:jobs {
        """
            + "\n".join([f"<{job['job_iri']}> wal:status wal:done ." for job in jobs])
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
        data=job_update,
    )

    print(r)
    print(r.text)

    r.raise_for_status()


def jobs_failed(jobs: list[dict]):

    triples = []

    for job in jobs:
        triples += f"<{job['job_iri']}> wal:status wal:failed ."
        if "error_report" in job:
            triples += f"<{job['job_iri']}> wal:report \"\"\"{job['error_report']}\"\"\" ."


    job_update = dedent(
        PREFIXES + """
        INSERT DATA {
            GRAPH wag:jobs {
        """
            + "\n".join(triples)
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
        data=job_update,
    )

    print(r)
    print(r.text)

    r.raise_for_status()
