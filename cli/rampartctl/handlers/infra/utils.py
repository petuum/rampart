# Copyright 2023 Petuum, Inc. All Rights Reserved.

from ..utils import get_all_custom_objects, ListError


def get_all_infras(args):
    try:
        objects = get_all_custom_objects(args, "rampartinfras")
    except ListError as e:
        print(e.message.format("infrastructure components"))
    return objects
