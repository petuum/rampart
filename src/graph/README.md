## Component interface on the pods

On a component with the specification:
```
component_name:
  type: type_name
  inputs:
    input_1:
      type: "volume"
      config:
        mountPath: "some/path/1"
      flow: "volume_flow1"
    input_2:
      type: "pulsar"
      flow: "pulsar_flow1"
  outputs:
    output_1:
      type: "volume"
      config:
        mountPath: "some/path/2"
      flow: "volume_flow2"
    output_2:
      type: "pulsar"
      flow: "pulsar_flow2"
```

The following will be present on the pod:

```
ENV:
   RAMPART_INPUT_input_1: some/path/1
   RAMPART_INPUT_input_2: pulsar://<pulsar-topic-for-pulsar_flow1>
   RAMPART_INPUT_output_1: some/path/2
   RAMPART_INPUT_output_2: pulsar://<pulsar-topic-for-pulsar_flow2>
VolumeMounts:
   some/path/1 from edge-pvc (rw,path="<unique-path-for-volume_flow1>")
   some/path/2 from edge-pvc (rw,path="<unique-path-for-volume_flow2>")
```

The `edge-pvc` volume is attached, which for now covers all of the inputs and output volume mounts. Note: in the future, seperate volumes and volume-claims may be used for inputs and outputs in order to get read-only permissions for input edges.
