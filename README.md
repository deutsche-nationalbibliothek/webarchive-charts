# The Deployment of the Webarchive

> The setup is created for the DNB, so it will likely not run in your environment but maybe you can reuse parts of it and you may be able to play with it in a minikube.

These are Helm charts.

Requirements:
- A [Kubernetes](https://kubernetes.io/) cluster, e.g. [minikube](https://minikube.sigs.k8s.io/).
- [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl) configured to access your cluster.
- [Helm](https://helm.sh/) to install the charts.
- [Task](https://taskfile.dev/) to make some things easier. (optional)

## Structure

The structure of the repository should in some way represent the structure of the setup.
For now it would start as a mono repository with the overall setup with services and might be split up in smaller repositories resp. charts using [chart dependencies](https://helm.sh/docs/topics/charts/#chart-dependencies).

## Start with Minikube

```
$ task setup:minikube
# Installed the mock data (task install:mock:example-data)
# Enables the ingress addon (minikube addons enable ingress)
$ task install
# Install the mocked ils and the playback to the minikube
```

Note: If you need to interoperate with the docker-host inside the minikube, run `eval $(minikube docker-env)`.

## Start with Open Shift

This assumes you have an aras interface (which exists probably only a the DNB).

```
$ ENV=dnb task install:playback
```

## Playback (pywb)

[Pywb](https://github.com/webrecorder/pywb) is served from the `pywb-service` respectively through the `pywb-ingress`.


## WARC Handling

The downloading, recompression, and indexing is currently done in an init Container.
This is no good idea but works for now.
The collection at the DNB requires the recompression step as they are not compressed record based.


## TODO

- Software:
  - playback:
    - solrwayback
  - Index
    - OutbackCDX
  - Object Storage (cache)
  - Validation
- Best Practices:
  - liveness check
  - readiness check

https://www.redhat.com/en/blog/9-best-practices-for-deploying-highly-available-applications-to-openshift
https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/

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
