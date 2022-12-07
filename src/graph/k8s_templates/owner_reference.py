# Copyright 2023 Petuum, Inc. All Rights Reserved.

from .name_decorator import use_kubernetes_name


@use_kubernetes_name
def owner_reference_template(name, uid, kind, api):
    return [{"apiVersion": api,
             "controller": False,
             "blockOwnerDeletion": True,
             "kind": kind,
             "name": name,
             "uid": uid}]
