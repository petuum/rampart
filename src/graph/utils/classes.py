# Copyright 2023 Petuum, Inc. All Rights Reserved.

import copy
from dataclasses import dataclass, field
from typing import List
from enum import Enum


class GraphPhase(Enum):
    """Enum describing phases of a Rampart graph"""
    NONE = "None"
    PARSING = "Parsing"
    VALIDATION = "Validation"
    DEPLOYMENT = "Deployment"
    TEARDOWN = "Teardown"

    def __str__(self):
        return self.value


class BaseError(Exception):
    def __init__(self, errors):
        self._errors = errors

    @property
    def errors(self):
        try:
            return copy.deepcopy(self._errors)
        except TypeError:
            return self._errors


class ValidationError(BaseError):
    """
    Class representing issues with the graph, equivalent to compilation failure

    Forms a monad with a set of sub-errors, the set map function and set union
    for join.
    """
    def __init__(self, errors):
        super().__init__(errors)

    def __str__(self):
        result = "The following errors occured during validation:\n"
        for error in self._errors:
            result += str(error)
            result += "\n\n"
        return result


class DeploymentError(BaseError):
    """
    Class representing a set of errors while deploying the graph

    Forms a monad with a set of sub-errors, the set map function and set union
    for join.
    """
    def __init__(self, errors):
        super().__init__(errors)

    def __str__(self):
        result = "The following errors occured during deployment:\n"
        for error in self._errors:
            result += str(error)
            result += "\n\n"
        return result


def collect_errors(results, error_cls=None):
    """
    Acts as the monadic join over both ValidationError and DeploymentError (seperately).
    Use this to combine multiple Validation/DeploymentError into one.

    `results` can include ValidationError/DeploymentError instances, normal exceptions,
    and non-exception values.

    Some notes:

    * normal exceptions will get wrapped in the error_cls and merged together with the BaseErrors
    * only one of ValidationError and DeploymentError can be present in `results`
    * if neither ValidationError nor DeploymentError are present, error_cls is used to wrap
      normal exceptions
    * if no exceptions are in `results`, `results` are returned instead

    args:
        results (list): list of errors and values to combine
        error_cls (BaseError subclass | None): BaseError class to use by default. Defaults to
                                               DeploymentError
    """

    # This is the monadic unit
    errors = set()
    for result in results:
        if isinstance(result, BaseError):
            if not error_cls:
                error_cls = type(result)
            elif not isinstance(result, error_cls):
                raise RuntimeError(
                    "Cannot mix deployment and validation steps. "
                    "This is a Rampart controller error; please report this bug")
            errors = errors.union(result.errors)
        elif isinstance(result, Exception):
            errors.add(result)

    if errors:
        if not error_cls:
            error_cls = DeploymentError
        raise error_cls(errors)
    return results


async def validate_dict(dictionary, *args, **kwargs):
    """Call `validate` on dict values and raise all ValidationError's if any."""
    result = {}
    errors = set()
    for key, value in dictionary.items():
        try:
            result[key] = await value.validate(*args, **kwargs)
        except ValidationError as e:
            errors = errors.union(e.errors)

    if errors:
        raise ValidationError(errors)

    return result


class Either:
    """
    Either monad:
    Values of either can be a success with some value or failure with an error message
    `bool(Success(x))` evaluates to `True` for all values `x`
    `bool(Failure(x))` evaluates to `False` for all values `x`
    """
    class Success:
        def __init__(self, value):
            self._value = value

        @property
        def value(self):
            return self._value

        def __bool__(self):
            return True

    class Failure:
        def __init__(self, error_value):
            self._error_value = error_value

        @property
        def error_value(self):
            return self._error_value

        def __bool__(self):
            return False


@dataclass
class SubprocessArgs:
    """Class for passing arguments to a subprocess exec."""
    exec_args: List[str] = field(default_factory=list)
    stdin_input: str = ""

    def __hash__(self) -> int:
        all_args = [str(val) for val in self.exec_args]
        all_args.append(str(self.stdin_input))
        return hash('%'.join(all_args))
