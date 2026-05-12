import pytest

from main import app, store


@pytest.fixture(autouse=True)
def clear_store():
    store.items.clear()
    yield
    store.items.clear()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "metrics-collector"
    assert "uptime_seconds" in data


def test_post_metric_success(client):
    payload = {"source": "host-1", "name": "cpu.load", "value": 0.42}
    resp = client.post("/api/metrics", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["source"] == "host-1"
    assert data["name"] == "cpu.load"
    assert data["value"] == 0.42
    assert "timestamp" in data


def test_post_metric_records_into_store(client):
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 1})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 2})
    resp = client.get("/api/metrics")
    data = resp.get_json()
    assert data["total"] == 2


def test_post_metric_rejects_missing_body(client):
    resp = client.post("/api/metrics", data="", content_type="application/json")
    assert resp.status_code == 400


def test_post_metric_rejects_non_object_body(client):
    resp = client.post("/api/metrics", json=[1, 2, 3])
    assert resp.status_code == 400


def test_post_metric_rejects_blank_source(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "   ", "name": "n", "value": 1},
    )
    assert resp.status_code == 400
    assert "source" in resp.get_json()["error"]


def test_post_metric_rejects_non_string_source(client):
    resp = client.post(
        "/api/metrics",
        json={"source": 123, "name": "n", "value": 1},
    )
    assert resp.status_code == 400


def test_post_metric_rejects_overlong_source(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "MAX_SOURCE_LENGTH", 5)
    resp = client.post(
        "/api/metrics",
        json={"source": "x" * 10, "name": "n", "value": 1},
    )
    assert resp.status_code == 400


def test_post_metric_rejects_blank_name(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "s", "name": "", "value": 1},
    )
    assert resp.status_code == 400
    assert "name" in resp.get_json()["error"]


def test_post_metric_rejects_non_numeric_value(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "s", "name": "n", "value": "abc"},
    )
    assert resp.status_code == 400
    assert "value" in resp.get_json()["error"]


def test_post_metric_rejects_boolean_value(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "s", "name": "n", "value": True},
    )
    assert resp.status_code == 400


def test_post_metric_rejects_overlarge_value(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "s", "name": "n", "value": 1e30},
    )
    assert resp.status_code == 400


def test_post_metric_accepts_explicit_timestamp(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "s", "name": "n", "value": 1, "timestamp": 1234567.0},
    )
    assert resp.status_code == 201
    assert resp.get_json()["timestamp"] == 1234567.0


def test_post_metric_rejects_negative_timestamp(client):
    resp = client.post(
        "/api/metrics",
        json={"source": "s", "name": "n", "value": 1, "timestamp": -1},
    )
    assert resp.status_code == 400


def test_store_eviction(client, monkeypatch):
    monkeypatch.setattr(store, "max_items", 3)
    for i in range(5):
        client.post(
            "/api/metrics",
            json={"source": "s", "name": "n", "value": i},
        )
    resp = client.get("/api/metrics")
    data = resp.get_json()
    assert data["total"] == 3
    values = [m["value"] for m in data["metrics"]]
    assert values == [2.0, 3.0, 4.0]
