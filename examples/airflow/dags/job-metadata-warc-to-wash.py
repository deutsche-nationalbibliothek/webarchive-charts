from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import dag, task

sparql_update_endpoint = "http://webarchive-fuseki:3030/ds/update"


metadata_warc_to_wash_update = """
prefix wa: <https://webarchiv.dnb.de/>
prefix bibo: <http://purl.org/ontology/bibo/>
prefix dc: <http://purl.org/dc/elements/1.1/>
prefix dct: <http://purl.org/dc/terms/>
prefix foaf: <http://xmlns.com/foaf/0.1/>
prefix schema: <https://schema.org/>
prefix lv: <http://purl.org/lobid/lv#>
prefix dowarc: <https://github.com/DOWARC/dowarc#>

insert {
    graph wa:warc {
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
            dc:relation ?website, ?warcinfo, ?warcfile ;
            dc:source ?seedUrl ;
            dct:created ?date ;
            dct:isPartOf ?website ;
            dct:source ?seedUrl ;
            foaf:primaryTopic ?seedUrl ;
            lv:webPageArchived ?seedUrl .

        ?seedUrl a schema:WebPage .
    }
} where {
    graph wa:warc {
        ?warcfile dct:relation ?request, ?response .

        ?request dowarc:WARC-Target-URI ?seedUrl ;
            dowarc:WARC-Type "request" ;
            dowarc:WARC-Concurrent-To ?response ;
            dowarc:WARC-Warcinfo-ID ?warcinfo .

        ?response dowarc:WARC-Date ?date ;
            dowarc:WARC-Type "response" ;
            dowarc:WARC-Target-URI ?seedUrl ;
            dowarc:WARC-Date ?date ;
            dowarc:WARC-Warcinfo-ID ?warcinfo .

        bind("webarchiv.dnb.de" as ?archive_domain)
        bind(iri(concat("urn:pwid:", ?archive_domain, ":", str(?date), ":page:", str(?seedUrl))) as ?pwid)
        # the date does not yet work for pwids
        bind(UUID() as ?snapshot)
        bind(UUID() as ?website)
    }
}
"""

metadata_updates = [metadata_warc_to_wash_update]


@dag(
    schedule=None,  # "@once"
    description="Update WARC Metadata",
    tags=["wacli"],
)
def job_metadata_warc_to_wash():

    @task
    def metadata_warc_to_wash():
        import requests

        for update in metadata_updates:
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

    metadata_warc_to_wash()


job_metadata_warc_to_wash()
