# MockILS

This is the mocked integrated library system. It should resemble the infrastructure available at some library in which the webarchive system would be deployed.

In particular it provides a repository interface to retrieve WARC files.

## Subpath Deployment
See: https://kubernetes.io/docs/concepts/services-networking/ingress/#the-ingress-resource

## Notes for the future

At some point the [setup behind a TLS termination proxy](https://fastapi.tiangolo.com/deployment/docker/#behind-a-tls-termination-proxy) might be relevant.
