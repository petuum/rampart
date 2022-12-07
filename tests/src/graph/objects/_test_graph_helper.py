# Copyright 2023 Petuum, Inc. All Rights Reserved.
import kubernetes_asyncio as kubernetes


def generate_namespace(name):
    return kubernetes.client.V1Namespace(
        "v1", "Namespace", kubernetes.client.V1ObjectMeta(name="name"))


def generate_rampart_graphs():
    return [{
        "metadata": {
            "name": "test-graph-2",
            "namespace": "default"},
        "spec": {
            "deploy": True,
            "graph": {
                "flows": {},
                "components": {
                    "c1": {
                        "namespace": "test1"},
                    "c2": {}}}}}, {
        "metadata": {
            "name": "testname",
            "namespace": "testnamespace"},
        "spec": {
            "deploy": True,
            "graph": {
                "flows": {},
                "components": {
                    "component2": {}}}}}]
