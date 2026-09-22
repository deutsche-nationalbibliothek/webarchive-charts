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
JOBSTATUS_NAMESPACE = BASE_IRI + "standards/vocab/jobstatus#"
DALAJOBS_NAMESPACE = BASE_IRI + "standards/vocab/datalakejobs#"

PREFIXES = dedent(f"""
    PREFIX wapplan: <{PROV_BASE_IRI}>
    PREFIX wal: <{WAL_NAMESPACE}>
    PREFIX wag: <{GRAPH_BASE_IRI}>
    PREFIX dalajobs: <{DALAJOBS_NAMESPACE}>
    PREFIX filestatus: <{FILESTATUS_NAMESPACE}>
    PREFIX jobstatus: <{JOBSTATUS_NAMESPACE}>

    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX bibo: <http://purl.org/ontology/bibo/>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX dc: <http://purl.org/dc/elements/1.1/>
    PREFIX dct: <http://purl.org/dc/terms/>
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX schema: <https://schema.org/>
    PREFIX lv: <http://purl.org/lobid/lv#>
    PREFIX dowarc: <https://github.com/DOWARC/dowarc#>
    """)

PREFIXES + """
filestatus:clean rdfs:label "clean" .
filestatus:indexed rdfs:label "indexed" .
filestatus:metadata_extracted rdfs:label "Metadata Extracted" .
"""

PREFIXES + """
jobstatus:done rdfs:label "done" .
jobstatus:failed rdfs:label "failed" .
jobstatus:skip rdfs:label "skip" .
"""

PREFIXES + """
wapplan:oGet
"""

PREFIXES + """
wal:fileStatus
wal:jobStatus
wal:File
wal:Job
wal:bucket
wal:filename
wal:idn
"""

PREFIXES + """
dalajobs:RecompressJob rdfs:label "Recompress Job" .
dalajobs:IndexJob rdfs:label "Index Job" .
dalajobs:MetadataExtractJob rdfs:label "Metadata Extract Job" .
dalajobs:ArasPullJob rdfs:label "Aras Pull Job" .
"""

@task
def get_jobs(
    projection: str = [],
    rdf_type: str = "wal:Job",
    properties: dict = {},
    triple_pattern: str = "",
    limit: int = 5,
):

    job_query = dedent(
        PREFIXES + f"""
    SELECT ?job {" ".join(f"?{var}" for var in projection)} {{
        GRAPH wag:jobs {{
            ?job a {rdf_type} ;
    """
        + ";\n".join([f"{prop[0]} {prop[1]}" for prop in properties.items()])
        + " . "
        + """
            FILTER NOT EXISTS {
                ?job wal:jobStatus ?status .
                VALUES ?status { jobstatus:done jobstatus:failed jobstatus:skip }
            }
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
def job_done(job: dict | None = None):
    return _jobs_done([job])


@task(trigger_rule="all_done")
def jobs_done(jobs: list[dict] | None = None):
    return _jobs_done(jobs)


def _jobs_done(jobs: list[dict]):

    job_update = dedent(
        PREFIXES + """
        INSERT DATA {
            GRAPH wag:jobs {
        """
            + "\n".join([f"<{job['job_iri']}> wal:jobStatus jobstatus:done ." for job in jobs])
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

def job_failed(context):
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("job_failed was called")
    print(context)
    task_instance = context["task_instance"]
    # Can we get remote_pod from the exception or from the task_instance?
    print(task_instance)
    job_iri = task_instance.xcom_pull(key="job")
    print(f"job {job_iri} failed")
    exception = context.get("exception")
    # We want to get from AirflowException > remote_pod.status.container_statuses[name=base].state.terminated.reason
    # if AirflowException
    import json

    remote_pod_string = "".join(exception.args.splitlines()[1:])
    print(remote_pod_string)
    remote_pod = json.loads(remote_pod_string)
    print(remote_pod)

    # if ApiException
    # TODO get Reason, HTTP response headers, and HTTP response body

    print(f"job_iri: {job_iri}")
    report_job_status([{"job_iri": job_iri}])

def report_job_status(jobs: list[dict]):

    triples = []

    for job in jobs:
        triples += f"<{job['job_iri']}> wal:jobStatus jobstatus:failed ."
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
