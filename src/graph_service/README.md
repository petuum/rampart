# Rampart Backend Service

## Overview

The Rampart Backend Service provides a backend with which the Rampart UI can deploy and manage the Rampart graphs deployed on a Kubernetes. The Rampart UI has the concept of `App`s, which are Rampart graphs with version history (including with the ability to revert, etc). Unfortunately, this abstraction does not match the abstraction maintained by `RampartGraph` custom resources, which do not maintain any sort of versioning. Therefore, the Rampart Backend Service needs to store the mapping between `App`s and `RampartGraph` custom resources.

The actual implementation is a [FastApi](https://fastapi.tiangolo.com) server rooted at `graph_service.run_app` using [TinyDB](https://tinydb.readthedocs.io/en/latest/) to store all of `App` and `RampartGraph` versioning state.

### Database Schemas:

Database for Apps, `app_db` (stored at `/etc/graphs/apps.json`):

```
{
    "app_id": id of the app used by the frontend
    "namespace": namespace of the graph
    "name": name of the graph
    "desc": description
    "active": Boolean, for if the graph is deployed
    "labels": labels
    "graph": json object used for creating the RampartGraph object
    "lastEditTimestamp": timestamp of last edit
    "lastDeploymentTimestamp": timestamp of last deployment
    "activeVersion": the currently deployed version (if active)
    "versionCount": the total number of versions
}
```

Database for graph versions, `graph_versions_db` (stored at `/etc/graphs/versions.json`):

```
{
    "namespace": namespace of the graph
    "name": name of the graph
    "version": current version
    "hash": hash of the graph specification
    "status": status of this graph version (e.g. Deployed)
    "active": Boolean, for if the graph is deployed
    "graph": json object used for creating the RampartGraph object
    "creationTimestamp": timestamp of when the version was created 
    "lastDeploymentTimestamp": timestamp of last deployment
}
```

Auxiliary database for [Grafana dashboards](https://grafana.com/docs/grafana/v8.4/http_api/dashboard/), `dashboard_db` (stored at `/etc/graphs/dashboard.json`):

```
{
    "app_id": id of the app used by the frontend
    "generation": generation of the application. Used to determine if the Grafana dashboards should be modified
    "dashboard_id": id for the Grafana dashboard
    "dashboard_uid": uid for the Grafana dashboard
    "dashboard_version": versions for the Grafana dashboard
    "urls": URL's for the Rampart UI to use to get the Grafana dashboard
}
```

Database for component charts and specifications available to the Rampart UI, `configs_db` (stored at `/etc/graphs/configs.json`):

```
{
    "id": id
    "title": name for the Rampart UI
    "config": config for the component chart and available options
    "type": for the Rampart UI
    "nodeType": for the Rampart UI
    "message": for the Rampart UI
    "creationTimestamp": timestamp of creation
    "lastModifiedTimestamp": timestamp of last modification
    "version": version of the component specification
}
```

### Code overview:

* The core of the code is in `graph_service.run_app`.
* Important helpers are located `graph_service.utils`, especially in `graph_service.utils.graphs`
* `graph_service.flows` runs in seperate pods (with multiple instances per graph). The main backend service will forward necessary requests to those services
* `graph_service.grafana` interacts with the Grafana API to create and fetch Grafana dashboards
