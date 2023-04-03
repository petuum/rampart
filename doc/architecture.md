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
  k8sapi["(kubernetes control plane)<br/>kube-apiserver<br/><br/>"]
  click k8sapi "https://kubernetes.io/docs/concepts/overview/components/#control-plane-components"
  subgraph rampart[Rampart system components]
    rgc[rampart-graph-controller]
    click rgc "https://github.com/petuum/rampart/blob/develop/src/graph/controller.py"
    rcw[rampart-conversion-webhook]
    click rcw "https://github.com/petuum/rampart/blob/develop/src/graph/validator.py"
    rmw[rampart-mutating-webhook]
    click rmw "https://github.com/petuum/rampart/tree/develop/src/mutating_webhook"
    rvw[rampart-validating-webhook]
    click rvw "https://github.com/petuum/rampart/blob/develop/src/graph/validator.py"
    rbe[rampart-backend-service]
    click rbe "https://github.com/petuum/rampart/tree/develop/src/graph_service"
    subgraph rig["Rampart infra graph"]
      api6[apisix-gateway]
      click api6 "https://github.com/petuum/rampart-apisix-chart"
      aic[apisix-ingress-controller]
      click aic "https://github.com/petuum/rampart-apisix-chart"
      adash[apisix-dashboard]
      click adash "https://github.com/petuum/rampart-apisix-chart"
      grafana
      click grafana "https://github.com/petuum/rampart-grafana"
      kuberay[kuberay-operator]
      click kuberay "https://github.com/petuum/rampart-kuberay-operator"
      rui[rampart-ui]
      click rui "https://github.com/petuum/rampart-ui-chart"
      rdash[rampart-dashboard]
      click rdash "https://github.com/petuum/rampart-k8s-dashboard"
      aic -- syncs --> api6
      adash -- manages --> api6
    end
    subgraph rdeps[Rampart system dependencies]
      hnc[hnc-manager]
      click hnc "https://github.com/kubernetes-sigs/hierarchical-namespaces"
      nfs[nfs-subdir-external-provisioner]
      click nfs "https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner"
    end
  end
  subgraph rugs["Rampart (user) graphs"]
    bup[batch-uploader]
    click bup "https://github.com/petuum/rampart-batch-uploader"
    bex[batch-executor]
    click bex "https://github.com/petuum/rampart-batch-executor"
    gs[generic-service]
    click gs "https://github.com/petuum/rampart-generic-service"
    other[ohter components...]
    flows["(flows)"<br/>file volume<br/>repository<br/>...]
    click flows "https://github.com/petuum/rampart/blob/develop/src/graph/objects/edge.py"
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

Note, the rampart system components are linked to their respective repositories.

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
