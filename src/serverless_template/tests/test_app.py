# Copyright 2023 Petuum, Inc. All Rights Reserved.

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
