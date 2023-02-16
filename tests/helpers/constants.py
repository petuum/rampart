# Copyright 2023 Petuum, Inc. All Rights Reserved.
import os


_username = os.environ.get("REGISTRY_USERNAME", "")
_password = os.environ.get("REGISTRY_PASSWORD", "")
_address = os.environ.get("REGISTRY_ADDRESS", "")
_registry_template = "https://{}" + _address
if _username and _password:
    REGISTRY_URL = _registry_template.format(f"{_username}:{_password}@")
elif _username or _password:
    # both "user:@" and ":pass@" are valid
    REGISTRY_URL = _registry_template.format(f"{_username}:{_password}@")
else:
    REGISTRY_URL = _registry_template.format("")
