# Copyright 2023 Petuum, Inc. All Rights Reserved.

from abc import ABC, abstractmethod
from functools import total_ordering


class BaseElement(ABC):

    def __init__(self, metadata):
        self._metadata = metadata
        self._validated = False

    @abstractmethod
    async def validate(self):
        return

    @property
    def name(self):
        """Human readable name of the element. May not be unique"""
        return self._metadata.name

    @property
    def namespace(self):
        """Human readable namespace of the element. May not be unique"""
        return self._metadata.namespace

    @property
    def uid(self):
        """Unique ID of the element"""
        return self._metadata.uid

    @property
    def validated(self):
        return self._validated

    @property
    def metadata(self):
        return self._metadata

    @abstractmethod
    async def deploy(self):
        """Deploys the element on the cluster. In the case of failure,
           does not tear down any partial deployment"""
        return


@total_ordering
class KubernetesName():
    def __init__(self, name):
        if isinstance(name, KubernetesName):
            self._original_view = name.original_view
            self._kubernetes_view = name.kubernetes_view
            self._rampart_view = name.rampart_view
        else:
            self._original_view = name
            self._kubernetes_view = name.replace("_", "-")
            self._rampart_view = name.replace("-", "_")

    def __bool__(self):
        return self._original_view != ""

    def __str__(self):
        return self._rampart_view

    def __lt__(self, other):
        if isinstance(other, KubernetesName):
            return self.original_view < other.original_view
        return str(self) < str(other)

    def __eq__(self, other):
        if isinstance(other, KubernetesName):
            return self.original_view == other.original_view
        return str(self) == str(other)

    def __hash__(self):
        return hash(self._rampart_view)

    def __repr__(self):
        return f"KubernetesName({self._original_view})"

    @property
    def original_view(self):
        return self._original_view

    @property
    def kubernetes_view(self):
        return self._kubernetes_view

    @property
    def rampart_view(self):
        return self._rampart_view


class Metadata():
    def __init__(self, namespace, name, uid):
        if isinstance(namespace, Metadata):
            self._namespace = namespace
        else:
            if not namespace:
                namespace = "None"
            self._namespace = KubernetesName(namespace)
        self._name = KubernetesName(name)
        self._uid = uid

    def __str__(self):
        return f"{self.namespace}/{self.name.kubernetes_view} (uid: {self.uid})"

    def __repr__(self):
        return f"Metadata({repr(self.namespace)}, {repr(self.name)}, {repr(self.uid)})"

    def __eq__(self, other):
        if not isinstance(other, Metadata):
            return False
        return (
            self.namespace == other.namespace and
            self.name == other.name and
            self.uid == other.uid)

    def __hash__(self):
        return hash((self.namespace, self.name, self.uid))

    def copy(self):
        return Metadata(self.namespace, self.name, self.uid)

    @property
    def namespace(self):
        return self._namespace

    @property
    def name(self):
        return self._name

    # For use when this object is used as a namespace for another Metadata object
    @property
    def kubernetes_view(self):
        return self.name.kubernetes_view

    @property
    def rampart_view(self):
        return self.name.rampart_view

    @property
    def uid(self):
        return self._uid

    @uid.setter
    def uid(self, uid):
        self._uid = uid
