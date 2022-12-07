# Copyright 2023 Petuum, Inc. All Rights Reserved.

from .utils import Event, _inject_context

__all__ = [Event, _inject_context]


_inject_context()
del _inject_context
