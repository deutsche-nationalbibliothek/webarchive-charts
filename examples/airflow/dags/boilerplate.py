from airflow.sdk import task

sparql_query_endpoint = "http://webarchive-fuseki:3030/ds/query"
sparql_update_endpoint = "http://webarchive-fuseki:3030/ds/update"


@task
def get_jobs(
    projection: str = [],
    rdf_type: str = "wal:Job",
    properties: dict = {},
    triple_pattern: str = "",
    limit: int = 10,
):
    import requests
    from requests.exceptions import JSONDecodeError

    job_query = (
        f"""
    PREFIX wa: <https://webarchiv.dnb.de/>
    PREFIX wal: <https://d-nb.info/standards/elementset/wal#>
    SELECT ?job {" ".join(f"?{var}" for var in projection)} {{
        GRAPH wa:jobs {{
            ?job a {rdf_type} ;
    """
        + ";\n".join([f"{prop[0]} {prop[1]}" for prop in properties.items()]) + " . "
        + """
            FILTER NOT EXISTS { ?job wal:status wal:done }
        }"""
        + triple_pattern +
        f"""
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
            {"job_iri": job["job"]["value"], **{var: job[var]["value"] for var in projection}}
            for job in r.json()["results"]["bindings"]
        ]
    except JSONDecodeError:
        print("Error")
        print(job_query)
        print(r.text)
        pass


@task
def job_done(job: dict):
    return _jobs_done([job])


@task
def jobs_done(jobs: list[dict]):
    return _jobs_done(jobs)


def _jobs_done(jobs: list[dict]):
    import requests

    job_update = (
        """
    PREFIX wa: <https://webarchiv.dnb.de/>
    PREFIX wal: <https://d-nb.info/standards/elementset/wal#>
    INSERT DATA {
        GRAPH wa:jobs {
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
