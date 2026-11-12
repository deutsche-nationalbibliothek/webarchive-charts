from textwrap import dedent

from airflow.exceptions import AirflowSkipException
from airflow.sdk import Asset, Connection, task
from common_context import get_cc
from requests.exceptions import JSONDecodeError

cc, _ = get_cc()

## Uses the following connections
# sparql_update_default: sparql-update-connection-secret
# sparql_query_default: sparql-query-connection-secret

BASE_IRI = "https://d-nb.info/"

WEBARCHIVE_BASE_IRI = BASE_IRI + "webarchive/"
GRAPH_BASE_IRI = WEBARCHIVE_BASE_IRI + "graphs/"
FILE_BASE_IRI = WEBARCHIVE_BASE_IRI + "files/"

PROV_BASE_IRI = BASE_IRI + "provenance/webarchive/plan#"

WAL_NAMESPACE = BASE_IRI + "standards/elementset/wal#"
FILESTATUS_NAMESPACE = BASE_IRI + "standards/vocab/filestatus#"
JOBSTATUS_NAMESPACE = BASE_IRI + "standards/vocab/jobstatus#"
DALAJOBS_NAMESPACE = BASE_IRI + "standards/vocab/datalakejobs#"
DALAJOBS_ASSET_NAMESPACE = BASE_IRI + "standards/vocab/datalakejobs/"

LIFECYCLE = "http://purl.org/vocab/lifecycle/schema#"

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

(
    PREFIXES
    + """
filestatus:clean rdfs:label "clean" .
filestatus:indexed rdfs:label "indexed" .
filestatus:metadata_extracted rdfs:label "Metadata Extracted" .
"""
)

(
    PREFIXES
    + """
jobstatus:done rdfs:label "done" .
jobstatus:failed rdfs:label "failed" .
jobstatus:skip rdfs:label "skip" .
"""
)

(
    PREFIXES
    + """
wapplan:oGet
"""
)

(
    PREFIXES
    + """
wal:fileStatus
wal:jobStatus
wal:File
wal:Job
wal:bucket
wal:filename
wal:idn
"""
)

(
    PREFIXES
    + """
dalajobs:RecompressJob rdfs:label "Recompress Job" .
dalajobs:IndexJob rdfs:label "Index Job" .
dalajobs:MetadataExtractJob rdfs:label "Metadata Extract Job" .
dalajobs:ArasPullJob rdfs:label "Aras Pull Job" .
"""
)


job_creator_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "UpdateJobs")
arras_pull_job_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "ArasPullJob")
recompress_job_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "RecompressJob")
metadataextract_job_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "MetadataExtractJob")
titlebasicwash_job_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "TitledataBasicWashJob")
titleextract_job_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "TitledataExtractJob")
index_job_asset = Asset(uri=DALAJOBS_ASSET_NAMESPACE + "IndexJob")


@task
def get_jobs(
    projection: str = [],
    rdf_type: str = "wal:Job",
    properties: dict = {},
    triple_pattern: str = "",
    limit: int = 5,
):
    sparql_query_conn = Connection.get("sparql_query_default")

    job_query = dedent(
        PREFIXES
        + f"""
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
    r = cc.sparql_query(sparql_query_conn, job_query)

    if not r.json()["results"]["bindings"]:
        raise AirflowSkipException

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


@task(outlets=[job_creator_asset])
def job_done(job: dict | None = None):
    return _jobs_done([job])


@task(trigger_rule="all_done", outlets=[job_creator_asset])
def jobs_done(jobs: list[dict] | None = None):
    return _jobs_done(jobs)


def _jobs_done(jobs: list[dict]):

    sparql_update_conn = Connection.get("sparql_update_default")

    job_update = dedent(
        PREFIXES
        + """
        INSERT DATA {
            GRAPH wag:jobs {
        """
        + "\n".join(
            [f"<{job['job_iri']}> wal:jobStatus jobstatus:done ." for job in jobs]
        )
        + """
            }
        }
        """
    )

    r = cc.sparql_update(sparql_update_conn, job_update)

    print(r)
    print(r.text)

    r.raise_for_status()


def job_failed(context):
    """This method is used to analyze and categorize failed tasks.
    A task is usually
    """
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

    print("remote_pod name: ", remote_pod.get("metadata").get("name"))
    container_statuses = remote_pod.get("status").get("container_statuses")
    base_status = [status for status in container_statuses if status["name"] == "base"]
    print("reson: ", base_status.get("state").get("terminated").get("reason"))

    # if ApiException
    # TODO get Reason, HTTP response headers, and HTTP response body

    print(f"job_iri: {job_iri}")
    report_job_status([{"job_iri": job_iri}])

    # finally we have to decide if the task should be rerun:
    # https://airflow.apache.org/docs/apache-airflow/stable/howto/dag-level-retry-via-callback.html
    # but we have to limit the retries:
    # https://airflow.apache.org/docs/apache-airflow/stable/howto/dag-level-retry-via-callback.html#clear-retry-limiting


def report_job_status(jobs: list[dict]):

    sparql_update_conn = Connection.get("sparql_update_default")

    triples = []

    for job in jobs:
        triples += f"<{job['job_iri']}> wal:jobStatus jobstatus:failed ."
        if "error_report" in job:
            triples += f'<{job["job_iri"]}> wal:report """{job["error_report"]}""" .'

    job_update = dedent(
        PREFIXES
        + """
        INSERT DATA {
            GRAPH wag:jobs {
        """
        + "\n".join(triples)
        + """
            }
        }
        """
    )

    r = cc.sparql_update(sparql_update_conn, job_update)

    print(r)
    print(r.text)

    r.raise_for_status()


@task
def update_file_status(job: dict, status: str, cc) -> None:
    """Update file status in wag:data graph.

    Args:
        job: Job dict with 'source_file' (string or list)
        status: Status IRI (e.g., "filestatus:metadata_extracted")
        cc: common_context instance (uses default if None)
    """
    sparql_update_conn = Connection.get("sparql_update_default")

    source_files = job["source_file"]
    if isinstance(source_files, str):
        source_files = [source_files]

    updates = "\n".join([f"<{f}> wal:fileStatus {status} ." for f in source_files])

    file_update = dedent(f"""
        {PREFIXES}
        INSERT DATA {{
            GRAPH wag:data {{
                {updates}
            }}
        }}
    """)

    r = cc.sparql_update(sparql_update_conn, file_update)
    r.raise_for_status()

    return job


@task
def record_file_outputs(
    job: dict,
    prov_iri: str,
    cc,
    initial_status: str | None = None,
) -> None:
    """Register file outputs generated/converted by a job with full provenance.

    Creates file entities in wag:data and provenance relations in wag:prov.
    Optionally sets initial file status.

    Args:
        job: Job dict with keys:
            - 'files': list of {filename, bucket}
            - 'job_iri': IRI of the job
            - 'source_file': optional source file IRI(s) for wasDerivedFrom
        prov_iri: IRI of the provenance plan/actor
        cc: common_context instance (uses default if None)
        initial_status: Optional status to set (e.g., "filestatus:clean")
    """
    sparql_update_conn = Connection.get("sparql_update_default")

    files = job["files"]
    job_iri = job["job_iri"]

    # Build file data
    file_data = []
    for f in files:
        filename = f["filename"]
        bucket = f.get("bucket", "")
        file_iri = (
            FILE_BASE_IRI + bucket + "/" + filename
            if bucket
            else FILE_BASE_IRI + filename
        )
        file_data.append({"iri": file_iri, "filename": filename, "bucket": bucket})

    # Build data graph triples
    data_triples = "\n".join(
        [
            f'<{f["iri"]}> a wal:File ; wal:filename "{f["filename"]}"; wal:bucket "{f["bucket"]}" .'
            for f in file_data
        ]
    )

    if initial_status:
        data_triples += "\n" + "\n".join(
            [f"<{f['iri']}> wal:fileStatus {initial_status} ." for f in file_data]
        )

    # Build provenance triples
    prov_triples = "\n".join(
        [
            f"<{f['iri']}> prov:wasGeneratedBy <{job_iri}> ; prov:wasAttributedTo {prov_iri} ."
            for f in file_data
        ]
    )

    # Add wasDerivedFrom if source file provided
    if "source_file" in job:
        source_files = job["source_file"]
        if isinstance(source_files, str):
            source_files = [source_files]
        if len(source_files) == len(file_data):
            prov_triples += "\n" + "\n".join(
                [
                    f"<{file_data[i]['iri']}> prov:wasDerivedFrom <{source}> ."
                    for i, source in enumerate(source_files)
                ]
            )

    # Combine into single SPARQL update
    update = dedent(f"""
        {PREFIXES}
        INSERT DATA {{
            GRAPH wag:data {{
                {data_triples}
            }}
            GRAPH wag:prov {{
                {prov_triples}
            }}
        }}
    """)

    r = cc.sparql_update(sparql_update_conn, update)
    r.raise_for_status()

    return job
