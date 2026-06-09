# The Deployment of the Webarchive

> The setup is created for the DNB, so it will likely not run in your environment, but maybe you can reuse parts of it, and you may be able to play with it in a minikube.

These are Helm charts.

Requirements:
- A [Kubernetes](https://kubernetes.io/) cluster, e.g. [minikube](https://minikube.sigs.k8s.io/).
- [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl) configured to access your cluster.
- [Helm](https://helm.sh/) to install the charts.
- [Task](https://taskfile.dev/) to make some things easier. (optional)

## Structure

The structure of the repository should in a way represent the structure of the setup.
For now, it would start as a mono repository with the overall setup with services and might be split up in smaller repositories resp. charts using [chart dependencies](https://helm.sh/docs/topics/charts/#chart-dependencies).

## Start with Minikube

```
$ task setup:minikube
# Installed the mock data (task install:mock:example-data)
# Enables the ingress addon (minikube addons enable ingress)
$ task install
# Install the mocked ils and the playback to the minikube
# Once it is running add the Airflow DAGs
$ task install:copy-example-dags
```

Note: If you need to interoperate with the docker-host inside the minikube, run `eval $(minikube docker-env)`.

## Start with Open Shift

This assumes you have an aras interface (which exists probably only at the DNB).

```
$ ENV=dnb task install
```

## Playback (pywb)

[Pywb](https://github.com/webrecorder/pywb) is served from the `pywb-service` respectively through the `pywb-ingress`.


## Workflows and WARC Handling

The downloading, recompression, and indexing are done as Jobs, that are orchestrated in an RDF graph and executed by Apache Airflow.
Files are stored in an S3.
Currently, the WARC files are all recompressed which is required for our data as it is not compressed record based.

## TODO

- Software
  - Job overview
- Workflow Steps
  - Validation
  - Metadata Extraction
- Best Practices:
  - liveness check
  - readiness check
- Ingress for airflow, fuseki, versitygw
- Error handling:
  - For failing jobs report job as failed with the following task in airflow
  - Store errors in graph
  - Validation, see above
- Graph handling:
  - combine fuseki and metadata graph

## Current Environment

```
Containers with * are init containers
(block the init process but are cleaned after they have exited).

┌──────────────────┐  ┌──────────────────┐
│📦 PWID resolver  │.>│📦   Playback     │ pywb-app
└──────────────────┘  └──────────────────┘
                               ∧
                               │
                      ┌──────────────────┐
                      │📁Playback Cache  │ .Values.webarchiveDirectory
                      └──────────────────┘
                               ∧
                               │
                      ┌──────────────────┐
                      │📦    Index*      │ wb-manager-add
                      └──────────────────┘
                               ∧
                               │
                      ┌──────────────────┐
                      │📁  WARC Cache    │ .Values.warcDirectory
                      └──────────────────┘
                               ∧
                               │
                      ┌──────────────────┐ wacli-recompress-warcs
                      │📦  Recompress*   │ $ wacli recompress-warcs
                      └──────────────────┘
                               ∧
                               │
                      ┌──────────────────┐
                      │📁  RAW Cache     │ .Values.rawWarcDirectory
                      └──────────────────┘
                               ∧
                               │
┌──────────────────┐  ┌──────────────────┐ wacli-load-warcs
│ Repository (aras)│─>│📦    Fetch*      │ $ wacli load-warcs
└──────────────────┘  └──────────────────┘
                               ∧
                               │
                      ┌──────────────────┐
                      │📄️  Graph Cache   │ .Values.websiteGraphFile
                      └──────────────────┘
                               ∧
                               │
┌──────────────────┐  ┌──────────────────┐ wacli-load-graph
│  Catalog/SPARQL  │─>│📦    Query*      │ $ wacli load-graph
└──────────────────┘  └──────────────────┘
```

## Conceptual Figure of the Data Flow of WARC Files

```
┌──────────────────┐  ┌──────────────────┐   ┌──────────────────┐
│     Crawling     │  │     Playback     │<..│  PWID resolver   │
└──────────────────┘  └──────────────────┘   └──────────────────┘
         │                     ∧
         ∨                     │
┌──────────────────┐  ┌──────────────────┐
│    Validation    │  │      Index       │
└──────────────────┘  └──────────────────┘
         │                     ∧
         ∨                     │
┌──────────────────┐  ┌──────────────────┐
│      Cache       │─>│      Cache       │
└──────────────────┘  └──────────────────┘
         │                     ∧
         ∨                     │
┌──────────────────┐  ┌──────────────────┐
│      Ingest      │  │   (Validation)   │
└──────────────────┘  └──────────────────┘
         │                     ∧
         ∨                     │
┌────────────────────────────────────────┐─>┌──────────────────┐
│               Repository               │  │    Validation    │
└────────────────────────────────────────┘<─└──────────────────┘
```

# Kubernetes/Helm

The repository is a helm chart with dependencies and subcharts.


## Kubernetes Dependencies

### Apache Airflow (Workflows)

The setup uses the [helm chart provided by the apache airflow project](https://airflow.apache.org/docs/helm-chart/) and [extends it according to the documentation](https://airflow.apache.org/docs/helm-chart/stable/extending-the-chart.html).

To nicely integrate secrets and connections we need to [follow the documentation](https://airflow.apache.org/docs/apache-airflow-providers-cncf-kubernetes/stable/secrets-backends/kubernetes-secrets-backend.html).

- [Repository](https://github.com/airflow-helm/charts)
- [README](https://github.com/airflow-helm/charts/blob/main/charts/airflow/README.md)
- [values.yaml](https://github.com/airflow-helm/charts/blob/main/charts/airflow/values.yaml)

### VersityGW (S3 Storage)

The setup uses the [helm chart provided by versity](https://github.com/versity/versitygw).

- [Repository](https://github.com/versity/versitygw)
- [README](https://github.com/versity/versitygw/blob/main/chart/README.md)
- [values.yaml](https://github.com/versity/versitygw/blob/main/chart/values.yaml)

### Apache Jena Fuseki (RDF Graph Store)

The setup includes an [Apache Jena Fuseki RDF Graph Store](https://jena.apache.org/documentation/fuseki2/) using the [helm chart provided by zazuko](https://artifacthub.io/packages/helm/zazuko/fuseki).

- [Repository](https://github.com/zazuko/helm-charts)
- [README](https://github.com/zazuko/helm-charts/blob/main/zazuko/fuseki/README.md)
- [values.yaml](https://github.com/zazuko/helm-charts/blob/main/zazuko/fuseki/values.yaml)

## Best Practices

These need to be implemented:

- https://www.redhat.com/en/blog/9-best-practices-for-deploying-highly-available-applications-to-openshift
- https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/

## Debugging Notes

To access some internal port, you can use port forwarding. In the Taskfile some respective tasks are specified.
