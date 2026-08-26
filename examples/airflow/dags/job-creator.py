from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task
from boilerplate import PREFIXES

sparql_update_endpoint = "http://webarchive-fuseki:3030/ds/update"


recompress_update = PREFIXES + """
INSERT {
    GRAPH wag:jobs {
        ?job a wal:Job, dalajobs:RecompressJob ;
            wal:file ?file .
    }
} WHERE {
    ?file a wal:File ;
        prov:wasAttributedTo wapplan:oGet .

    FILTER NOT EXISTS {
        ?recompressedFile a wal:File ;
            wal:fileStatus filestatus:clean ;
            prov:wasDerivedFrom ?file .
    }

    FILTER NOT EXISTS {
        ?recompressJob a dalajobs:RecompressJob ;
            wal:file ?file .
    }

    BIND (UUID() as ?job)
}
"""

index_update = PREFIXES + """
INSERT {
    GRAPH wag:jobs {
        ?job a wal:Job, dalajobs:IndexJob ;
            wal:file ?file .
    }
} WHERE {
    ?file a wal:File ;
        wal:fileStatus filestatus:clean .

    FILTER NOT EXISTS {
        ?file wal:fileStatus filestatus:indexed .
    }

    FILTER NOT EXISTS {
        ?recompressJob a dalajobs:IndexJob ;
            wal:file ?file .
    }

    BIND (UUID() as ?job)
}
"""

metadata_extract_update = PREFIXES + """
INSERT {
    GRAPH wag:jobs {
        ?job a wal:Job, dalajobs:MetadataExtractJob ;
            wal:file ?file .
    }
} WHERE {
    ?file a wal:File ;
        wal:fileStatus filestatus:clean .

    FILTER NOT EXISTS {
        ?file wal:fileStatus filestatus:metadata_extracted .
    }

    FILTER NOT EXISTS {
        ?recompressJob a dalajobs:MetadataExtractJob ;
            wal:file ?file .
    }

    BIND (UUID() as ?job)
}
"""

job_updates = [recompress_update, index_update, metadata_extract_update]


@dag(
    schedule=None,  # "@once"
    description="Creates jobs",
    tags=["wacli"],
)
def job_creator():

    @task
    def create_jobs():
        import requests

        for update in job_updates:
            r = requests.post(
                sparql_update_endpoint,
                auth=("admin", "admin"),
                headers={
                    "Accept": "application/sparql-results+json,*/*;q=0.9",
                    "Content-Type": "application/sparql-update",
                },
                data=update,
            )

            print(r)
            print(r.text)

            r.raise_for_status()

    create_jobs()


job_creator()
