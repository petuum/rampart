# Copyright 2023 Petuum, Inc. All Rights Reserved.

import copy
import kubernetes_asyncio as kubernetes
import yaml
import yaml.scanner
import yamale

from .edge import FlowType, IOPart, VariadicEdgeSpec, SimpleEdgeSpec
from .base_types import BaseElement, Metadata
from ..utils.classes import ValidationError
from ..utils.deployment import require_validated

from ..constants import COMP_ANNOTATIONS_SCHEMA

kubernetes.config.load_incluster_config()
custom_api = kubernetes.client.CustomObjectsApi()
core_api = kubernetes.client.CoreV1Api()


class ComponentSpec(BaseElement):
    """
    This class manages all the information about the component that is specified in the remote
    helm chart.

    If Components are values, then ComponentSpecs are types.
    """
    def __init__(self, annotations, repo_name, chart_name, chart_version, chart_url):

        _name = f"component-spec-{chart_name}-{chart_version}-{repo_name}"
        _uid = f"component-spec-{chart_name}-{chart_version}-{repo_name}"

        metadata = Metadata(None, _name, _uid)
        super().__init__(metadata)

        self._chart_name = chart_name
        self._chart_version = chart_version

        self._repo_name = repo_name
        self._chart_reference = f"{self._repo_name}/{self._chart_name}"
        self._chart_url = chart_url

        self._input_specs = {}
        self._output_specs = {}

        # TODO: support versioning
        self._provides = {}
        self._requires = {}

        self._annotations = annotations

    def _update_io_specs(self, io_specs, io_part: IOPart):
        """
        Internal function to generalize handling inputs and outputs

        Args:
            io_specs: specifications about what the edges should be
            io_part (edge.IOPart): whether this is for inputs or outputs
        """
        for io_spec in io_specs:
            io_name = io_spec["name"]
            io_type = FlowType[io_spec["type"].upper()]
            target = self._input_specs if io_part is IOPart.INPUT else self._output_specs
            if io_name in target:
                raise ValidationError({
                    f"{io_part.name.capitalize()} {io_name} cannot occur multiple times"
                    f" in the definition of component {self._metadata.name}"})
            if io_name[-1] == "*":
                target[io_name] = VariadicEdgeSpec(io_type, io_name[:-1], io_part, io_spec)
            else:
                target[io_name] = SimpleEdgeSpec(io_type, io_name, io_part, io_spec)

    @property
    def input_specs(self):
        return copy.deepcopy(self._input_specs)

    @property
    def output_specs(self):
        return copy.deepcopy(self._output_specs)

    @property
    def provides(self):
        return copy.deepcopy(self._provides)

    @property
    def requires(self):
        return copy.deepcopy(self._requires)

    @property
    def version(self):
        return self._chart_version

    @property
    def chart_reference(self):
        return self._chart_reference

    async def validate(self):
        """
        Throws a `ValidationError` if this component specification or any of its children are
        invalid. This call must be made before any function with the `@required_validated` decorator
        is called.
        """
        if self._validated:
            return

        if not self._annotations:
            self._input_specs = {}
            self._output_specs = {}
        else:
            try:
                yamale_data = yamale.make_data(content=self._annotations)
                yamale.validate(COMP_ANNOTATIONS_SCHEMA, yamale_data)
                annotations = yamale_data[0][0]
                self._update_io_specs(io_specs=annotations["inputs"], io_part=IOPart.INPUT)
                self._update_io_specs(io_specs=annotations["outputs"], io_part=IOPart.OUTPUT)
                # TODO: replace None with version
                self._provides = {provided: None for provided in annotations.get("provides", {})}
                self._requires = {requires: None for requires in annotations.get("requires", {})}
            except (yamale.YamaleError, IndexError, yaml.scanner.ScannerError) as error:
                raise ValidationError({f"Error parsing chart annotations for "
                                       f"({self._chart_name}, {self._chart_version}) at "
                                       f"{self._chart_url}, please make sure that your component "
                                       f" spec under 'annotations' is valid.\n{error}"})

        for spec in self._input_specs.values():
            await spec.validate()
        for spec in self._output_specs.values():
            await spec.validate()
        self._validated = True

    @require_validated
    async def deploy(self):
        pass
