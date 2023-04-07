# Rampart Architecture

Rampart is a platform to create and manage ML infrastructure as graphs
(RampartGraph as a kubernetes custom resource) on kubernetes clusters.
This higher level graph abstraction enables (eventually) transparent
scalability across heterogeneous kubernetes clusters from multiple cloud
vendors and on-prem datacenters.

## Typical deployed rampart components
```mermaid
flowchart
subgraph k8s[Kubernetes cluster]
  k8sapi[<a href='https://kubernetes.io/docs/concepts/overview/components/#control-plane-components'>kubernetes control plane</a><br/>kube-apiserver<br/><br/>]
  subgraph rampart[Rampart system components]
    rgc[<a href='https://github.com/petuum/rampart/blob/develop/src/graph/controller.py'>rampart-graph-controller</a>]
    rcw[<a href='https://github.com/petuum/rampart/blob/develop/src/graph/validator.py'>rampart-conversion-webhook</a>]
    rmw[<a href='https://github.com/petuum/rampart/tree/develop/src/mutating_webhook'>rampart-mutating-webhook</a>]
    rvw[<a href='https://github.com/petuum/rampart/blob/develop/src/graph/validator.py'>rampart-validating-webhook</a>]
    rbe[<a href='https://github.com/petuum/rampart/tree/develop/src/graph_service'>rampart-backend-service</a>]
    subgraph rig[Rampart infra graph]
      api6[<a href='https://github.com/petuum/rampart-apisix-chart'>apisix-gateway</a>]
      aic[<a href='https://github.com/petuum/rampart-apisix-chart'>apisix-ingress-controller</a>]
      adash[<a href='https://github.com/petuum/rampart-apisix-chart'>apisix-dashboard</a>]
      grafana[<a href='https://github.com/petuum/rampart-grafana'>grafana</a>]
      kuberay[<a href='https://github.com/petuum/rampart-kuberay-operator'>kuberay-operator</a>]
      rui[<a href='https://github.com/petuum/rampart-ui-chart'>rampart-ui</a>]
      rdash[<a href='https://github.com/petuum/rampart-k8s-dashboard'>rampart-dashboard</a>]
      aic -- syncs --> api6
      adash -- manages --> api6
    end
    subgraph rdeps[Rampart system dependencies]
      hnc[<a href='https://github.com/kubernetes-sigs/hierarchical-namespaces'>hnc-manager</a>]
      nfs[<a href='https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner'>nfs-subdir-external-provisioner</a>]
    end
  end
  subgraph rugs["Rampart (user) graphs"]
    bup[<a href='https://github.com/petuum/rampart-batch-uploader'>batch-uploader</a>]
    bex[<a href='https://github.com/petuum/rampart-batch-executor'>batch-executor</a>]
    gs[<a href='https://github.com/petuum/rampart-generic-service'>generic-service</a>]
    other[ohter components...]
    flows[<a href='https://github.com/petuum/rampart/blob/develop/src/graph/objects/edge.py'>flows</a><br/>file volume<br/>repository<br/>...]
    bup <--> flows
    bex <--> flows
    gs <--> flows
    other <--> flows
  end
  style rdeps stroke-dasharray: 4 4
  style rampart stroke-dasharray: 4 4
  style rig stroke-dasharray: 4 4
  style rugs stroke-dasharray: 4 4
  rgc <--> k8sapi
  k8sapi --> rcw
  k8sapi --> rmw
  k8sapi --> rvw
  rbe --> k8sapi
  rdash --> k8sapi
  hnc <--> k8sapi
  nfs <--> k8sapi
  kuberay --> k8sapi
  aic --> k8sapi
  grafana --> k8sapi
  api6 --> rbe
  api6 --> rui
  api6 --> rdash
  api6 --> grafana
  api6 -- routes --> rugs
  rgc -. configures .-> grafana
  rvw -. validates .-> rugs
  rmw -. mutates .-> rugs
  rcw -. migrates .-> rugs
end
style k8sapi stroke-dasharray: 4 4
oidc["(oidc providers)"<br/>keycloak<br/>auth0<br/>...]
k8sclient(("(k8s clients)"<br/>kubectl<br/>helm<br/>...)) --> k8sapi
webclient(("(web clients)"<br/>browsers<br/>curl<br/>...)) --> api6
k8sapi <-- auth --> oidc
k8sclient <-- auth --> oidc
api6 <-- auth --> oidc
```

Note, some of the links, e.g., components in rampart infra graph and
rampart (user) graphs, might return 404, until their open source work is
complete.

## Typical rampart graph lifecyle sequences
```mermaid
sequenceDiagram
  participant client
  participant k8s as k8s control plane
  participant rgc as rampart-graph-controller
  participant rvw as rampart-validating-webhook
  participant rmw as rampart-mutating-webhook
  participant kubelet
  client ->> k8s: submit graphs
  k8s ->> rvw: validate graphs
  rvw -->> k8s: OK or error
  k8s -->> client: submit result (OK or error)
  k8s ->> rgc: schedule graphs if validated
  rgc ->> k8s: child k8s resources of graphs
  k8s ->> rmw: modify child resources of graphs if needed
  rmw ->> k8s: modified child resources of graphs
  k8s ->> kubelet: schedule resources
  kubelet ->> k8s: update resource statuses
  k8s ->> rgc: statuses of child resources of graphs
  rgc ->> k8s: update statuses of graphs
```

Note, graph conversion sequence for graph backward compatibility is left out
for clearer illustration of the most common sequence.
