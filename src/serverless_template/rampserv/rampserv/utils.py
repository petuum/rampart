# Copyright 2023 Petuum, Inc. All Rights Reserved.

import builtins
import logging


class Event:
    """
    Defines the event body used by handler functions.
    """
    def __init__(self, body, request=None):
        self.body = body

        if request:
            self.headers = request.headers
            self.app = request.app
            self.url = request.url
            self.base_url = request.base_url
            self.method = request.method
            self.query_params = request.query_params
            self.receive = request.receive
            self.state = request.state
            self.client = request.client
            self.cookies = request.cookies


class Context:
    """
    Context class for ASGI interface. The user can use this to store user data
    and logging functionality.
    """
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        self.logger.addHandler(ch)
        self.user_data = {}


def _inject_context():
    builtins.context = Context()
