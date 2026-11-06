"""API contract checks (rubric: FastAPI Serving).

- /health returns 200                               (passes out of the box)
- missing required field returns HTTP 422           (passes out of the box: Pydantic)
- valid /predict returns a schema-valid response    (passes once you implement predict)
- valid /predict_batch returns one result per input (passes once you implement batch)
"""
from tests.conftest import load_fixture


RESPONSE_FIELDS = ("fraud_probability", "is_fraud", "model_version", "latency_ms")


def assert_valid_prediction(data):
    for field in RESPONSE_FIELDS:
        assert field in data, f"missing '{field}' in response"
    assert 0.0 <= data["fraud_probability"] <= 1.0
    assert data["is_fraud"] in (0, 1)


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_predict_missing_field_returns_422(client):
    body = load_fixture("predict_sample.json")["missing_amount"]
    resp = client.post("/predict", json=body)
    assert resp.status_code == 422


def test_predict_returns_valid_schema(client):
    body = load_fixture("predict_sample.json")["valid"]
    resp = client.post("/predict", json=body)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert_valid_prediction(resp.json())


def test_predict_batch_returns_one_prediction_per_input(client):
    body = load_fixture("predict_sample.json")["valid"]
    resp = client.post("/predict_batch", json=[body, body])
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), "expected /predict_batch to return a JSON list"
    assert len(data) == 2, "expected one prediction per input transaction"
    for prediction in data:
        assert_valid_prediction(prediction)
