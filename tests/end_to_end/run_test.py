# Copyright 2023 Petuum, Inc. All Rights Reserved.

import kubernetes
import subprocess
import time
import urllib
import yaml

from graph_generator import simple, complete, bipartite


timeout = 10000


def run_test(namespace, name, graph, incluster=False):
    if incluster:
        kubernetes.config.load_incluster_config()
    else:
        kubernetes.config.load_kube_config()
    graph_api = kubernetes.client.CustomObjectsApi()
    core_api = kubernetes.client.CoreV1Api()

    expected = graph.edges()
    graph = graph.to_yaml(name, namespace)
    graph_api.create_namespaced_custom_object(
        "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", graph)
    for i in range(int(timeout)):
        time.sleep(1)
        try:
            graph_status = graph_api.get_namespaced_custom_object_status(
                "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", name)
            if "status" in graph_status and graph_status["status"]["phase"] == "Deployed":
                break
            elif "status" in graph_status and graph_status["status"]["phase"] == "Failed":
                raise RuntimeError("Graph deployment failed")
        except kubernetes.client.rest.ApiException as e:
            if e.status == 404:
                pass
    else:
        raise RuntimeError("Graph deployment timed out")

    components = graph_status["status"]["componentNamespaces"]
    edges = {}
    for comp_namespace in components:
        pod = core_api.list_namespaced_pod(
            comp_namespace, label_selector="app=component-test-component")
        assert len(pod.items) == 1
        pod_name = pod.items[0].metadata.name
        # TODO: clean up this subprocess
        exception = None
        if incluster:
            with urllib.request.urlopen(
                    f"http://{pod_name}.{comp_namespace}.pod.cluster.local:8000") as response:
                edges_response = response.read().decode("utf-8")
        else:
            try:
                pf = subprocess.Popen(
                    ["kubectl", "port-forward", "-n", comp_namespace, pod_name, "8000:8000"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(2)
                with urllib.request.urlopen("http://localhost:8000/inputs") as response:
                    edges_response = response.read().decode("utf-8")
            except Exception as e:
                # Need to run the finally clause before raising this
                exception = e
            finally:
                pf.kill()

        if exception:
            raise exception

        component_name, volume_edges, pulsar_edges, repo_edges = yaml.safe_load(edges_response)
        edges[component_name] = volume_edges, pulsar_edges, repo_edges

    assert (len(edges) == len(expected))

    for component, (volume_edges, pulsar_edges, repo_edges) in edges.items():
        for index, edges in enumerate([volume_edges, pulsar_edges, repo_edges]):
            for input_edge, outputs in edges.items():
                if outputs and type(outputs[0]) == str:
                    outputs = [yaml.safe_load(output) for output in outputs]
                assert (sorted(outputs) == sorted(expected[component][index][input_edge])), \
                    (sorted(outputs), sorted(expected[component][index][input_edge]))
    graph_api.delete_namespaced_custom_object(
        "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", name)
    return True


if __name__ == "__main__":
    print("Starting tests")
    assert run_test("default", "test-simple", simple())
    print("Simple graph passed")
    assert run_test("default", "test0", bipartite(2, 4))
    print("K_2,4 passed")
    assert run_test("default", "test1", bipartite(6, 8))
    print("K_6,8 passed")
    assert run_test("default", "test2", bipartite(10, 20))  # Note: currently fails
    print("K_10,20 passed")
    assert run_test("default", "test3", complete(10, 3, 2, 4))  # Note: currently fails
    print("K_10 passed")
