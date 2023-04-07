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

from app.app import app
from starlette.testclient import TestClient

client = TestClient(app)


def test_sentiment_analyzer():
    request_body = {
        "sent_str": "This is a good book.",
        "check_response": "true"
    }
    response = client.post("/rampserv/predict", json=request_body)
    assert response.status_code == 200
    response_body = response.json()
    assert response_body == {"neg": 0.0, "neu": 0.58, "pos": 0.42,
                             "compound": 0.4404}


def test_check_response():
    request_body = {
        "check_response": "true"
    }
    response = client.post("/rampserv/respond", json=request_body)
    assert response.status_code == 200
    response_body = response.json()
    assert response_body == {"response": "true"}
