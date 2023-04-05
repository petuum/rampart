# Rampart
Rampart is an open system built on top of Kubernetes for MLOps that allows easy provisioning of custom infrastructure from templates. It is designed with the principles of composability, automation, and scalability, for developers to enable simple infrastructure management, modular pipeline development, seamless deployment, and experiment management.

Developers can use the drag-and-drop GUI to spin up infrastructure from a template and get started on a new project in minutes, without any help from a system admin. As an extensible system for interoperability, Rampart can be used to deploy any software (i.e., OSS, third-party software, or any custom code) in addition to a library of native Rampart components as parts of custom infrastructure.

Its Infrastructure-as-a-Graph approach represents commonly used AIML application patterns as components, such as Batch Data Uploader, Batch Executor, Ray cluster and Tensorboard visualizer. Components are connected through “flows” which can be NFS volumes, pulsar streaming or repositories. Infrastructure graphs can be composed quickly and replicated, customized, deployed, or updated live.

![](/doc/images/rampart-ui.png)

Rampart is one of a series of tools that make up the MLOps OSS repertoire that Petuum releases. We are excited to introduce more useful tools to the developer community in the coming days.

# Installation
This is covered by a separate repo which is coming soon.

# Usage
Rampart does many things. The quickest way to familiarize with Rampart is by creating an MLOps deployment, which you can usually start with deploying a graph. You can import a graph represented in the YAML below:
```yaml
apiVersion: rampart.petuum.com/v1beta2
kind: RampartGraph
metadata:
  name: demo
spec:
  graph:
    components:
      batch-uploader:
        type: batch-uploader
        chart:
          name: batch-uploader
          repo: rampart-repo
          version: latest
        config:
          imagePullSecrets:
            - name: stagingsecret
        inputs: {}
        outputs:
          output_1:
            type: volume
            flow: batch-input
    flows:
      batch-input:
        type: volume
        config:
          size: 1Gi
```
This is a simple Rampart Graph demonstrating how a component called Batch Uploader is connected to a Volume Flow named `batch-input`.

> **Note:**
> A Rampart Graph is deployed on a Kubernetes cluster as a [custom resource (CR)](https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/custom-resources/) named RampartGraph. The following command requires the [kubectl](https://kubernetes.io/docs/reference/kubectl/kubectl/) command line tool to run.

Run this code to deploy this graph:
```bash
kubectl apply -f <path/to/graph.yaml> -n default
```
Go to Rampart UI at `http://<node-ip>:30800/`

Use
```bash
curl -F "files[]=@<file-path>" -F "batch-name=1" -F "edge-name=output_1" http://<node-ip>:30800/default/demo/batch-uploader/multipart/upload-batch-atomic/
```
to upload a file. Where `<file-path>` is the path to any file you want to upload, and `<node-ip>` is the IP address of a cluster node. “succeeded” will be printed on the terminal when file uploading is completed.

# Contributing
Contributions are welcome! If you would like to contribute to Rampart OSS, please follow these steps:
1. Fork the repository.
2. Make your changes.
3. Submit a pull request.

# Open Source Progress

Open sourced repos:
- rampart controller

Coming soon:
- rampart helm
- Rampart GUI
- Rampart components

# Implemnetation
See the documentation for the [Rampart Controller](src/graph/README.md) and [Rampart Backend Service](src/graph_service/README.md) within this repository for details.
