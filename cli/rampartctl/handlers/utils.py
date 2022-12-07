# Copyright 2023 Petuum, Inc. All Rights Reserved.

import copy
import kubernetes


class ListError(Exception):
    def __init__(self, message):
        self._message = message

    @property
    def message(self):
        return copy.copy(self._message)


def get_all_custom_objects(args, object_plural):
    # args must contain mutually exclusive all_namespaces and namespace
    api = kubernetes.client.CustomObjectsApi()
    namespace_api = kubernetes.client.CoreV1Api()
    namespaces = namespace_api.list_namespace()
    namespaces = namespaces.items
    if args.all_namespaces:
        tasks = []
        for namespace in namespaces:
            tasks.append(api.list_namespaced_custom_object(
                "rampart.petuum.com", "v1beta1", namespace.metadata.name,
                object_plural, async_req=True))
        graphs = []
        for task in tasks:
            for dict_items in task.get()["items"]:
                graphs.append(dict_items)
        if not graphs:
            raise ListError("No {} found")
            return []
    else:
        if args.namespace not in [namespace.metadata.name for namespace in namespaces]:
            raise ListError(f"Namespace {args.namespace} does not exist")
            return []
        graphs = api.list_namespaced_custom_object(
            "rampart.petuum.com", "v1beta1", args.namespace, object_plural)["items"]
        if not graphs:
            # Can't use format string here
            print("No {} found in namespace " + args.namespace)
            return []
    return graphs
