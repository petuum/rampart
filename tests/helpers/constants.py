# Copyright 2023 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

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
