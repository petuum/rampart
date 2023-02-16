# Copyright 2023 Petuum, Inc. All Rights Reserved.

from typing import Dict

from pydantic import BaseModel


class RedeployModel(BaseModel):
    appId: str
    version: str
    deployed: bool


class GraphModel(BaseModel):
    apiVersion: str
    kind: str
    metadata: Dict
    spec: Dict


class NodeConfigsModel(BaseModel):
    title: str
    config: Dict
    type: str
    nodeType: str
    message: str = None
