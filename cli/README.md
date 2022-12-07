# Introduction (for developers)

`rampartctl` is a command line tool that uses the [Kubernetes Python API](https://github.com/kubernetes-client/python) to interact with Rampart graphs and component repositories. The primary emphasis is that all standard use and basic troubleshooting can be done with `rampartctl` only, without relying on `kubectl`.

When you add a user feature to Rampart, you should also add a new or edit an existing `rampartctl` subcomponent.

# Implementation details:

`rampartctl` uses [`argparse`](https://docs.python.org/3/library/argparse.html) with [subparsers](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser.add_subparsers) to parse and handle all of the various commands users may use. `cli/rampartctl/main.py` attaches the subparser to the main parser and sets up the Kubernetes client cluster configuration and authentication.

To add a new command, you will need to do the following:

1. Create an argparse handler function (generally with name: `handle_<verb>_<object>`. E.g. `handle_create_graph`). This function will contain all of the actual functionality.
2. Create a function with the following format:

```
def register_<verb>_<object>(subparsers):
    parser = subparsers.add_parser(...)
    parser.add_argument(
        "name", nargs="?", ...)
    namespace = parser_describe.add_mutually_exclusive_group(required=False)
    namespace.add_argument(
        "-n", "--namespace", type=str, default="default",
        help="namespace to restrict the rampart graphs listed")
    namespace.add_argument(
        "-A", "--all-namespaces", action='store_true',
        help="list across all namespaces, overrides `--namespace`")
    ... # more arguments as needed
    parser.set_defaults(handler=handle_<verb>_<object>)
```

This function will create the subparser when called from `cli/rampartctl/main.py` and attach the handler function.

3. Import `register_<verb>_<object>` in `cli/rampartctl/main.py`, and call it on the executor list

In case of errors in your handler function, print a useful message and call `exit(1)`
