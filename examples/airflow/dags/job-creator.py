from textwrap import dedent

from airflow.sdk import AssetAlias, Connection, dag, task
from boilerplate import (
    PREFIXES,
    index_job_asset,
    job_creator_asset,
    metadataextract_job_asset,
    recompress_job_asset,
    titlebasicwash_job_asset,
    titleextract_job_asset,
)
from common_context import get_cc

## Uses the following connections
# sparql_update_default: sparql-update-connection-secret

cc, _ = get_cc()

recompress = {
    "insert": dedent("""
        {
            GRAPH wag:jobs {
                ?job a wal:Job, dalajobs:RecompressJob ;
                    wal:file ?file .
            }
        }
        """),
    "condition": PREFIXES
    + dedent("""
        SELECT ?job ?file {
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
        """),
}

index = {
    "insert": dedent("""
        {
            GRAPH wag:jobs {
                ?job a wal:Job, dalajobs:IndexJob ;
                    wal:file ?file .
            }
        }
        """),
    "condition": PREFIXES
    + dedent("""
        SELECT ?job ?file  {
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
        """),
}

metadata_extract = {
    "insert": dedent("""
        {
            GRAPH wag:jobs {
                ?job a wal:Job, dalajobs:MetadataExtractJob ;
                    wal:file ?file .
            }
        }
        """),
    "condition": PREFIXES
    + dedent("""
        SELECT ?job ?file {
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
        """),
}

metadata_wash_convert = {
    "insert": dedent("""
        {
            GRAPH wag:jobs {
                ?job a wal:Job, dalajobs:TitledataBasicWashJob ;
                    wal:file ?file .
            }
        }
        """),
    "condition": PREFIXES
    + dedent("""
        SELECT ?job ?file {
            ?file a wal:File ;
                wal:fileStatus filestatus:metadata_extracted .

            FILTER NOT EXISTS {
                ?snapshot a lv:ArchivedWebPage ; dc:relation ?file .
            }

            FILTER NOT EXISTS {
                ?recompressJob a dalajobs:TitledataBasicWashJob ;
                    wal:file ?file .
            }

            BIND (UUID() as ?job)
        }
        """),
}

titledata_extract = {
    "insert": dedent("""
        {
            GRAPH wag:jobs {
                ?job a wal:Job, dalajobs:TitledataExtractJob ;
                    wal:file ?file .
            }
        }
        """),
    "condition": PREFIXES
    + dedent("""
        SELECT ?job ?file {
            ?file a wal:File ;
                wal:fileStatus filestatus:metadata_extracted .
            ?snapshot a lv:ArchivedWebPage ; dc:relation ?file .

            FILTER NOT EXISTS {
                ?file wal:fileStatus filestatus:titledata_extracted .
            }

            FILTER NOT EXISTS {
                ?recompressJob a dalajobs:TitledataExtractJob ;
                    wal:file ?file .
            }

            BIND (UUID() as ?job)
        }
        """),
}

job_updates = {
    recompress_job_asset: recompress,
    titleextract_job_asset: index,
    metadataextract_job_asset: metadata_extract,
    titlebasicwash_job_asset: metadata_wash_convert,
    index_job_asset: titledata_extract,
}


job_assetalias = AssetAlias("job-alias")


@dag(
    schedule=job_creator_asset,  # "@once"
    description="Creates jobs",
    tags=["wacli"],
)
def job_creator():

    @task(outlets=[job_assetalias])
    def create_jobs(*, outlet_events):
        sparql_query_conn = Connection.get("sparql_query_default")
        sparql_update_conn = Connection.get("sparql_update_default")

        for job_asset, insert_condition_dict in job_updates.items():
            insert = insert_condition_dict["insert"]
            condition = insert_condition_dict["condition"]

            condition_response = cc.sparql_query(sparql_query_conn, condition)
            condition_response.raise_for_status()

            if condition_response.json()["results"]["bindings"]:
                values = ""
                for binding in condition_response.json()["results"]["bindings"]:
                    values += f"""
                        ( <{binding["job"]["value"]}> <{binding["file"]["value"]}> )
                    """
                    values_clause = "VALUES (?job ?file) { " + values + " }"

                update = PREFIXES + f"INSERT {insert} WHERE {{ {values_clause} }}"

                update_response = cc.sparql_update(sparql_update_conn, update)

                update_response.raise_for_status()
                outlet_events[job_assetalias].add(job_asset)

    create_jobs()


job_creator()
