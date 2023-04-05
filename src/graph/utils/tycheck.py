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

def has_shared_prefix(paths):
    """
    Check if there exists paths p1, p2 in `paths` such that p1 is a prefix of p2.

    Algorithm:
    Repeatedly add paths to the trie/prefix tree, if we end on not a fresh leaf,
    then the current path is a prefix of a prexisting one. If we ever encounter
    a leaf while adding a path, then some prexisiting path is a prefix of the current one.
    Note: duplicates are covered by the second case.
    """
    trie = {}
    for path in paths:
        path = path.rstrip("/")
        current_node = trie
        directories = path.split("/")
        for directory in directories:
            if directory not in current_node:
                current_node[directory] = {}
            # We are at a leaf from a previous path. The previous path is a prefix of this one
            elif current_node[directory] == {}:
                return True
            current_node = current_node[directory]
        # We are at the leaf of the current path, but there is a previous path already here
        # The current path is a prefix of the previous one
        if current_node != {}:
            return True
    return False
