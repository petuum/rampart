# Rampart Controller

## Overview

The Rampart Controller serves as the [Kubernetes Controller](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/) for the RampartGraph custom resource. It contains three seperate components with the following rolls:

* Validator: A [Kubernetes Validating Admission Webhook](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/) that performs initial static validation on RampartGraph objects. Because Kubernetes has a strict timeout policy on requests to admission webhooks, and because this webhook must return before the Kubernetes response to create the graph is returned, the validator does not perform time-consuming checks. In particular, validation that requires the component helm charts (which requires the validator to download the chart) is skipped. Note that a graph that is rejected by the validator will not be actually created by Kubernetes: instead, the creation request will fail.
* Mutation Webhook: A [Kubernetes Mutating Admission Webhook](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/) that modifies all requests to create pods in the namespaces of Rampart graph components. As part of graph deployment, each component namespace will have a PodPreset object that defines what changes should be made to the pod to attach edges and flows. This mutation webhook then applies the pod and container specifications defined by the preset to all pods in the component. Please note that this code lives in `src/mutating_webhook` instead of `src/graph`.
* Controller: The actual core of the controller, sharing code with the Validator. This component listens for RampartGraph object creation, updates, and deletion, and modifies the cluster state to match the specified state. This is accomplished by a listener loop that enqueues tasks to synchronize graph state. The code to manage the loop and the tasks it spawns are located in `src/graph/controller.py`, while the code to validate, deploy, and teardown the Rampart graph and its components are located in the various files in `src/graph/objects/`. `src/graph/objects/graph.py` is the main file for graphs. In order to fully validate and deploy the components, the controller needs to handle local versions helm charts, akin to `helm repo add/update/remove` and `helm pull` in the command line. `src/graph/repository.py` manages these repositories and charts.

## Validation and Deployment

It is perhaps best to think of the controller as a compiler, except instead of taking and emitting code, it takes in yaml specifications via RampartGraph custom object and emits changes to the Kubernetes cluster.

The core of this functionality is provided by the `Graph` class (found in `src/graph/objects/graph.py`). Of note, there are two asynchronous functions: `validate` and `deploy`.

### Validation

Validation occurs via four phases:

1. Kubernetes rejects RampartGraph custom resources which are not valid yamls and do not meet the RampartGraph specification in the CRD. Currently, this is just that the graph contains `spec.graph.components`, `spec.graph.flows`, and an optional `spec.deploy`. This validation lives entirely outside of the Rampart Controller.
2. The graph is validated against the JSONSchema defined in `src/graph/graph.json`. This occurs in the both the validator and controller.
3. More complex static checks are performed. For example, references to flows in the components are checked for the correct type and mount paths are checked for validity.  This phase occurs in both the validator and controller.
4. Checks that require pulling the component helm charts are performed. This includes that the helm charts are reachable and valid and that the annotations contained within the component charts match the specifications of the graph. Because this phase can timeout (say due to connection issues or to downloading a large helm chart), this phase is only performed in the controller. Because this phase cannot cause graphs that fail phase 1-3 to become valid, the validator will produce false positives, but will not produce false negatives. Therefore there will be graphs that are created that fail with `ValidationError`, but there will not be any correct graphs that fail to become created.

Within the code itself, phase 2 is performed during instatiation of the `Graph` object by the classmethod `from_json`. Phases 3 and 4 are performed by the `validate` function, with phase 4 only performed when the argument `validate_specs` is set to `True`.

### Deployment

Once validation is completed, the controller can begin deployment of components and flows. To do this, it performs the following steps:

1. Deploy all of the subnamespaces that will contain the components (note: each component gets its own namespace)
2. Deploy all of the flows. Note that the actual body of volume flows do not exist per se, but are rather when two components using it write and read to the same place on a distributed filesystem
   a. Create Pulsar tenants, namespaces, and topics to house Pulsar flows
   b. Create all the auxiliary volume claimsm, deployments, and services to monitor volume flows
   c. Initialize the repository structure within the repository flows
3. Deploy all of the components
   a. Using the repositories pulled during validation, create a [helmfile](https://helmfile.readthedocs.io/en/latest/) configuration file to package all of the components, edges, and `config` fields together.
   b. Use `helmfile sync` deploy the components or update them if they already exist
   c. `helmfile sync` does not tear down releases, so we manually need to uninstall components that have been removed from the graph.

Note that this behavior is the same for both updates and fresh installs. Combining this idempotency in the controller code means that partial installs due to controller termination can be finished upon controller recreation.

![Rampart Validation and Deployment flowchart](/doc/images/rampart_deployment.svg)

### Teardown

As much as possible, teardown is handled by [Kubernetes ownerreferences](https://kubernetes.io/docs/concepts/overview/working-with-objects/owners-dependents/). However, components can install cluster-scoped resources. To handle this, the controller attaches a [finalizer](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/) to RampartGraph objects. When a request to delete an object is received by Kubernetes, the object will be given the metadata field `deletionTimestamp`. The controller will then use `helm uninstall` to remove the cluster-scoped objects for each component before deleting the rest of the Kubernetes objects created for the graph and removing the finalizer from the RampartGraph object.

## Class structure

The core functionality is contained within `objects.graph.Graph`, containing the following functions of note:

```python3
@classmethod
async def from_json(cls, graph_json, metadata, validate_specs=True, workdir=""):
    """Constructs a Graph instance from a yaml"""

async def validate(self, validate_specs):
    """Performs validation"""

@require_validated
async def _deploy_namespaces(self):
    """Deploys component namespaces"""

@require_validated
async def _deploy_edges(self):
    """Deploys flows"""

@require_validated
async def _deploy_componets(self):
    """
    Deploys the component helm charts. Calls `component.to_deployment_yaml` for each component.
    Also deploys all of the required objects to give the components access to their flows.
    This is the function that creates the helmfile subprocess to deploy all of the components
    """

@require_validated
async def deploy(self):
    """Calls the above three functions to deploy the graph"""

@require_validated
async def undeploy(self):
    """Performs teardowns for when `spec.deploy: false` in the graph yaml

@require_validated
async def teardown_old_namespaces(self):
    """Teardown old namespacess that are no longer part of the graph after an update"""

@require_validated
async def teardown_namespaces(self):
    """
    Performs a helm uninstall followed by namespace deletion.
    Occurs after the graph is marked for deletion and before the finalizers are removed
    """
```

Functionality for deploying the components themselves are contained within the class `objects.Component`:

```python3
async def validate(self, validate_specs):
    """Performs validation"""

@require_validated
async def to_deployment_yaml(self, workdir):
    """
    Writes the helmfile files needed to deploy the edges for this component to workdir.
    Returns the yaml objects that `objects.Graph` needs to deploy the component.
    Uses `to_deployment_yaml` from `objects.ComponentChart`
    """

@require_validated
async def deploy_sub_namespace(self, base_namespace, owner_reference):
    """Deploys the subnamespace that the component lives in."""

@require_validated
async def teardown(self, base_namespace):
    """Calls helm uninstall on the component chart and destroys the subnamespace"""
```

Each `objects.Component` instance contains an instance of `objects.ComponentChart` that handles
the helm chart and its settings.

```python3
@classmethod
async def from_yaml(cls, yaml_obj, graph_metadata):
    """Constructs an instance from a dictionary object"""

async def validate(self):
    """
    Validates this chart. If the remote repository for the chart is unreachable,
    for example, because of a misspelled URL or bad credentials, this will fail
    """

async def to_deployment_yaml(self, name, namespace, values, recreate_pods, deployment_kwargs, needs):
    """
    Returns a single entry for the `releases` field in the component helmfile for this graph.
    The `repository` field of the helmfile is instead created by `objects.Graph` by getting the
    chart names, urls, and pull settings from each of the `objects.ComponentChart` instances,
    as there may be duplicates.
    """
```

Edges and flows are implemented within `objects/edge.py`, with each type of flow and edge having its own subclass of
`BaseFlow` and `BaseEdge`.

Flows have the following major functions:

```python3
async def validate(self):
    """Does validation"""

@staticmethod
async def batch_deploy(flows, workdir, graph_metadata):
    """
    Deploys all of the elements of `flows` at once. Used because multiple flows of the same
    will generally share infrastructure
    """

@require_validated
async def deploy(self):
    """Only for Pulsar. Creates a single topic"""
```

Edges have the following functions and property:

```python3
async def validate(self):
    """Does validation"""

@property
@require_validated
def resource(self):
    """
    The string that is exposed in an environment variable to the pods in the component.
    E.g. mount paths, pulsar topics
    """

@require_validated
def create_k8s_objects(self, namespace, seen_flows):
    """
    Creates kubernetes objects needed for this edge.
    `seen_flows` removes duplication between edges with the same flow when needed.
    """

@require_validated
def create_pod_preset_values(self, seen_flows):
    """
    Adds values to podPreset and containerPreset to attach the flows to the components.
    `seen_flows` removes duplication between edges with the same flow when needed.
    """
```

## Component interface on the pods

On a component with the specification:
```
component_name:
  type: type_name
  chart: ...
  inputs:
    input_1:
      type: "volume"
      config:
        mountPath: "some/path/1"
      flow: "volume_flow1"
    input_2:
      type: "pulsar"
      flow: "pulsar_flow1"
  outputs:
    output_1:
      type: "volume"
      config:
        mountPath: "some/path/2"
      flow: "volume_flow2"
    output_2:
      type: "pulsar"
      flow: "pulsar_flow2"
```

The following will be present on the pod:

```
ENV:
   RAMPART_INPUT_input_1: some/path/1
   RAMPART_INPUT_input_2: pulsar://<pulsar-topic-for-pulsar_flow1>
   RAMPART_INPUT_output_1: some/path/2
   RAMPART_INPUT_output_2: pulsar://<pulsar-topic-for-pulsar_flow2>
VolumeMounts:
   some/path/1 from edge-pvc (r, path="<unique-path-for-volume_flow1>")
   some/path/2 from edge-pvc (rw,path="<unique-path-for-volume_flow2>")
```

The `edge-pvc` volume is attached, which for now covers all of the inputs and output volume mounts. Note: in the future, seperate volumes and volume-claims may be used for inputs and outputs in order to get read-only permissions for input edges.
