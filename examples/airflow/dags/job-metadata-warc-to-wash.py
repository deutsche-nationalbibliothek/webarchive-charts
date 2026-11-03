from airflow.sdk import Connection, dag, task, task_group
from boilerplate import PREFIXES, get_jobs, job_done
from boilerplate import titlebasicwash_job_asset as job_asset
from common_context import get_cc

## Uses the following connections
# sparql_update_default: sparql-update-connection-secret

cc, _ = get_cc()

metadata_warc_to_wash_update = (
    PREFIXES
    + """
prefix bibo: <http://purl.org/ontology/bibo/>
prefix dc: <http://purl.org/dc/elements/1.1/>
prefix dct: <http://purl.org/dc/terms/>
prefix foaf: <http://xmlns.com/foaf/0.1/>
prefix schema: <https://schema.org/>
prefix lv: <http://purl.org/lobid/lv#>
prefix dowarc: <https://github.com/DOWARC/dowarc#>

insert {
    graph wag:warc {
        ?website
            a bibo:Website ; # Website
            dc:type bibo:Website ;
            dc:relation ?seedUrl ;
            foaf:primaryTopic ?seedUrl .

        ?snapshot
            a lv:ArchivedWebPage ; # Zeitschnitt
            dc:type lv:ArchivedWebPage ;
            dc:identifier ?pwid ;
            dc:date ?date ;
            dc:relation ?website, ?request, ?warcinfo, ?warcfile ;
            dc:source ?seedUrl ;
            dct:created ?date ;
            dct:isPartOf ?website ;
            dct:source ?seedUrl ;
            foaf:primaryTopic ?seedUrl ;
            lv:webPageArchived ?seedUrl .

        ?seedUrl a schema:WebPage .
    }
} where {
    graph wag:warc {
        ?warcfile dct:relation ?request, ?response .

        ?request dowarc:WARC-Target-URI ?seedUrl ; # Seed Request
            dowarc:WARC-Type "request" ;
            dowarc:WARC-Concurrent-To ?response .

        ?response dowarc:WARC-Date ?date ; # Seed Response
            dowarc:WARC-Type "response" ;
            dowarc:WARC-Target-URI ?seedUrl ;
            dowarc:WARC-Date ?date .

        optional {
            ?request dowarc:WARC-Warcinfo-ID ?warcinfo .
            ?response dowarc:WARC-Warcinfo-ID ?warcinfo .
        }

        bind("webarchiv.dnb.de" as ?archive_domain)
        bind(concat(str(wag:warc), "/") as ?base)

        # the date does not yet work for pwids
        bind(if(TIMEZONE(?date) = "PT0S"^^xsd:dayTimeDuration, concat(strbefore(replace(str(?date), "Z", "+"), "+"), "Z"), concat(str(?date), "-INVALID")) as ?utc_date)
        bind(iri(concat("urn:pwid:", ?archive_domain, ":", str(?utc_date), ":page:", str(?seedUrl))) as ?pwid)

        bind(iri(concat(str(?base), sha256(concat(str(?pwid), str(?response))))) as ?snapshot)
        bind(iri(concat(str(?base), sha256(str(?seedUrl)))) as ?website)
    }
}
"""
)

metadata_updates = [metadata_warc_to_wash_update]

JOB_IRI_LOCAL_PART = "TitledataBasicWashJob"
JOB_TYPE_QNAME = "dalajobs:" + JOB_IRI_LOCAL_PART


@dag(
    schedule=job_asset,  # "@once"
    description="Update WARC Metadata",
    tags=["wacli"],
)
def job_metadata_warc_to_wash():

    @task_group(group_id="warc_to_wash_workflow")
    def warc_to_wash_workflow(job: dict):
        """Task group for a single TitledataBasicWashJob"""

        @task
        def metadata_warc_to_wash(job: dict):
            """
            TODO: get warc source_file from job and inject variable into sparql update
            """
            sparql_update_conn = Connection.get("sparql_update_default")

            for update in metadata_updates:
                r = cc.sparql_update(sparql_update_conn, update)

                print(r)
                print(r.text)

                r.raise_for_status()

        metadata_job = metadata_warc_to_wash(job=job)
        done_job = job_done(metadata_job)

        return done_job

    jobs = get_jobs(
        ["source_file"],
        JOB_TYPE_QNAME,
        {"wal:file": "?source_file"},
    )

    warc_to_wash_workflow.expand(job=jobs)


job_metadata_warc_to_wash()
