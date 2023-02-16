## Mutation webhook

This webhook watches for pod creations, and when a pod is created,
it modifies the pod spec to use the mutationpreset in that namespace.

Dictionaries/Lists will be merged between the two, with dictionary's
using the preset's value in case of key collisions. Note: this does not
support deeply nested merges.

Currently, it only supports a single mutationpreset per namespace,
and subnamespaces do not inherent from their parents. The former ideally
is fixed, but then that gets into a few tricky questions about precedence
in collisions.

### How to disable it for your pod
A pod with label key `rampart-disable-edges` is ignored regardless of its value.
Note: setting `rampart-disable-edges="true"` or something similar will still
disable the mutation since the value of this lable is ignored completely.

