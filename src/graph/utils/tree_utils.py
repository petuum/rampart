# Copyright 2023 Petuum, Inc. All Rights Reserved.

def recursive_merge(source, destination, merge_list=False):
    """
    Given a nested structure of dictionary and lists, recursively merge
    `source` into `destination`. If `merge_list` is true, lists are merged
    instead of replaced.

    `destination` is modified"""
    for key, value in source.items():
        if (key in destination and type(value) == dict
                and type(destination[key]) == dict):
            recursive_merge(value, destination[key], merge_list)
        elif (merge_list and key in destination and type(value) == list
                and type(destination[key]) == list):
            destination[key] = destination[key] + value
        else:
            destination[key] = value
