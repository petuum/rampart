# Copyright 2023 Petuum, Inc. All Rights Reserved.
from collections import defaultdict
from copy import deepcopy
from functools import reduce

import yaml
import yaml.representer


class DefaultDict(defaultdict):
    def __str__(self):
        return dict.__str__(self)

    def __repr__(self):
        return dict.__repr__(self)

    def delete(self, key):
        d = deepcopy(self)
        *path, key = key.split(".")
        reduce(defaultdict.__getitem__, path, d).pop(key, None)
        return d

    def add_or_edit(self, key, value):
        d = deepcopy(self)
        *path, key = key.split(".")
        reduce(defaultdict.__getitem__, path, d)[key] = value
        return d

    def to_yaml(self):
        return yaml.dump(self)


yaml.add_representer(DefaultDict, yaml.representer.SafeRepresenter.represent_dict)


def nested_dict(d=None):
    return DefaultDict(nested_dict, d or {})
