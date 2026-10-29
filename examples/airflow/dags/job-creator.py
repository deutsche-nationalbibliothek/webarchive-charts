from airflow.sdk import AssetAlias, Connection, dag, task
from boilerplate import (
    PREFIXES,
    index_job_asset,
    metadataextract_job_asset,
    recompress_job_asset,
    titleextract_job_asset,
)
from common_context import get_cc

## Uses the following connections
# sparql_update_default: sparql-update-connection-secret

cc, _ = get_cc()

recompress_update = (
    PREFIXES
    + """
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
)

index_update = (
    PREFIXES
    + """
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
)

metadata_extract_update = (
    PREFIXES
    + """
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
)

titledata_extract_update = (
    PREFIXES
    + """
INSERT {
    GRAPH wag:jobs {
        ?job a wal:Job, dalajobs:TitledataExtractJob ;
            wal:file ?file .
    }
} WHERE {
    ?file a wal:File ;
        wal:fileStatus filestatus:metadata_extracted .

    FILTER NOT EXISTS {
        ?file wal:fileStatus filestatus:titledata_extracted .
    }

    FILTER NOT EXISTS {
        ?recompressJob a dalajobs:TitledataExtractJob ;
            wal:file ?file .
    }

    BIND (UUID() as ?job)
}
"""
)

job_updates = {
    recompress_job_asset: recompress_update,
    titleextract_job_asset: index_update,
    metadataextract_job_asset: metadata_extract_update,
    index_job_asset: titledata_extract_update,
}


job_assetalias = AssetAlias("job-alias")

@dag(
    schedule=None,  # "@once"
    description="Creates jobs",
    tags=["wacli"],
)
def job_creator():

    @task(
        outlets=[job_assetalias]
    )
    def create_jobs(*, outlet_events):
        sparql_update_conn = Connection.get("sparql_update_default")

        for job_asset, update in job_updates.values():
            r = cc.sparql_update(sparql_update_conn, update)

            print(update)
            print(r)
            print(r.text)

            r.raise_for_status()
            outlet_events[job_assetalias].add(job_asset)

    create_jobs()


job_creator()
