# Copyright 2023 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

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
