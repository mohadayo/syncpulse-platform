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


def test_list_metrics_filter_by_source(client):
    client.post("/api/metrics", json={"source": "host-a", "name": "n", "value": 1})
    client.post("/api/metrics", json={"source": "host-b", "name": "n", "value": 2})
    resp = client.get("/api/metrics?source=host-a")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["metrics"][0]["source"] == "host-a"


def test_list_metrics_filter_by_name(client):
    client.post("/api/metrics", json={"source": "s", "name": "cpu", "value": 1})
    client.post("/api/metrics", json={"source": "s", "name": "mem", "value": 2})
    resp = client.get("/api/metrics?name=cpu")
    data = resp.get_json()
    assert data["total"] == 1
    assert data["metrics"][0]["name"] == "cpu"


def test_list_metrics_filter_by_time_range(client):
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 1, "timestamp": 100.0})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 2, "timestamp": 200.0})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 3, "timestamp": 300.0})
    resp = client.get("/api/metrics?since=150&until=250")
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1


def test_list_metrics_pagination(client):
    for i in range(5):
        client.post("/api/metrics", json={"source": "s", "name": "n", "value": i, "timestamp": float(i)})
    resp = client.get("/api/metrics?limit=2&offset=1&sort=timestamp")
    data = resp.get_json()
    assert data["total"] == 5
    assert data["count"] == 2
    values = [m["value"] for m in data["metrics"]]
    assert values == [1.0, 2.0]


def test_list_metrics_sort_value_desc(client):
    for v in [10.0, 30.0, 20.0]:
        client.post("/api/metrics", json={"source": "s", "name": "n", "value": v})
    resp = client.get("/api/metrics?sort=value&order=desc")
    values = [m["value"] for m in resp.get_json()["metrics"]]
    assert values == [30.0, 20.0, 10.0]


def test_list_metrics_rejects_invalid_sort(client):
    resp = client.get("/api/metrics?sort=bogus")
    assert resp.status_code == 400


def test_list_metrics_rejects_invalid_order(client):
    resp = client.get("/api/metrics?order=sideways")
    assert resp.status_code == 400


def test_list_metrics_rejects_invalid_limit(client):
    resp = client.get("/api/metrics?limit=0")
    assert resp.status_code == 400


def test_list_metrics_rejects_negative_offset(client):
    resp = client.get("/api/metrics?offset=-1")
    assert resp.status_code == 400


def test_list_metrics_rejects_until_before_since(client):
    resp = client.get("/api/metrics?since=200&until=100")
    assert resp.status_code == 400


def test_delete_metrics_success(client):
    client.post("/api/metrics", json={"source": "to_delete", "name": "n", "value": 1})
    client.post("/api/metrics", json={"source": "to_delete", "name": "n", "value": 2})
    client.post("/api/metrics", json={"source": "keep", "name": "n", "value": 3})

    resp = client.delete("/api/metrics?source=to_delete")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["deleted_count"] == 2

    remaining = client.get("/api/metrics").get_json()
    assert remaining["total"] == 1
    assert remaining["metrics"][0]["source"] == "keep"


def test_delete_metrics_not_found(client):
    resp = client.delete("/api/metrics?source=nonexistent")
    assert resp.status_code == 404


def test_delete_metrics_missing_source(client):
    resp = client.delete("/api/metrics")
    assert resp.status_code == 400


def test_delete_metrics_by_name_only(client):
    client.post("/api/metrics", json={"source": "s1", "name": "deleteme", "value": 1})
    client.post("/api/metrics", json={"source": "s2", "name": "deleteme", "value": 2})
    client.post("/api/metrics", json={"source": "s1", "name": "keep", "value": 3})

    resp = client.delete("/api/metrics?name=deleteme")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["deleted_count"] == 2
    assert data["name"] == "deleteme"
    assert "source" not in data

    remaining = client.get("/api/metrics").get_json()
    assert remaining["total"] == 1
    assert remaining["metrics"][0]["name"] == "keep"


def test_delete_metrics_by_time_range(client):
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 1, "timestamp": 100})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 2, "timestamp": 200})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 3, "timestamp": 300})

    resp = client.delete("/api/metrics?since=150&until=250")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["deleted_count"] == 1
    assert data["since"] == 150.0
    assert data["until"] == 250.0

    remaining = client.get("/api/metrics").get_json()
    assert remaining["total"] == 2
    timestamps = sorted(m["timestamp"] for m in remaining["metrics"])
    assert timestamps == [100.0, 300.0]


def test_delete_metrics_by_until_only_retention_use_case(client):
    """データ保持期限切れ削除のユースケース: 古いデータを until=cutoff で削除"""
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 1, "timestamp": 100})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 2, "timestamp": 500})
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 3, "timestamp": 1000})

    resp = client.delete("/api/metrics?until=500")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["deleted_count"] == 2

    remaining = client.get("/api/metrics").get_json()
    assert remaining["total"] == 1
    assert remaining["metrics"][0]["timestamp"] == 1000.0


def test_delete_metrics_combined_filters(client):
    client.post("/api/metrics", json={"source": "web", "name": "rps", "value": 1, "timestamp": 100})
    client.post("/api/metrics", json={"source": "web", "name": "rps", "value": 2, "timestamp": 500})
    client.post("/api/metrics", json={"source": "web", "name": "latency", "value": 50, "timestamp": 500})
    client.post("/api/metrics", json={"source": "db", "name": "rps", "value": 9, "timestamp": 500})

    resp = client.delete("/api/metrics?source=web&name=rps&since=200")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["deleted_count"] == 1

    remaining = client.get("/api/metrics").get_json()
    assert remaining["total"] == 3


def test_delete_metrics_rejects_invalid_since(client):
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 1})
    resp = client.delete("/api/metrics?since=not-a-number")
    assert resp.status_code == 400
    assert "since" in resp.get_json()["error"]


def test_delete_metrics_rejects_until_before_since(client):
    client.post("/api/metrics", json={"source": "s", "name": "n", "value": 1})
    resp = client.delete("/api/metrics?since=500&until=100")
    assert resp.status_code == 400


def test_delete_metrics_blank_name_rejected(client):
    resp = client.delete("/api/metrics?name=   ")
    assert resp.status_code == 400


def test_delete_metrics_returns_404_when_filters_match_nothing(client):
    client.post("/api/metrics", json={"source": "alive", "name": "n", "value": 1})
    resp = client.delete("/api/metrics?name=ghost")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["deleted_count"] == 0


def test_summary_basic(client):
    for v in [10.0, 20.0, 30.0]:
        client.post("/api/metrics", json={"source": "s", "name": "n", "value": v})
    resp = client.get("/api/metrics/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_metrics"] == 3
    assert len(data["series"]) == 1
    series = data["series"][0]
    assert series["count"] == 3
    assert series["min"] == 10.0
    assert series["max"] == 30.0
    assert series["avg"] == 20.0


def test_summary_percentiles(client):
    for i in range(1, 11):
        client.post("/api/metrics", json={"source": "s", "name": "n", "value": float(i * 10)})
    series = client.get("/api/metrics/summary").get_json()["series"][0]
    assert series["min"] == 10.0
    assert series["max"] == 100.0
    assert series["p50"] == 55.0
    assert series["p95"] >= 90.0
    assert series["p99"] >= 95.0


def test_summary_groups_by_source_name(client):
    client.post("/api/metrics", json={"source": "a", "name": "x", "value": 1})
    client.post("/api/metrics", json={"source": "a", "name": "y", "value": 2})
    client.post("/api/metrics", json={"source": "b", "name": "x", "value": 3})
    data = client.get("/api/metrics/summary").get_json()
    assert len(data["series"]) == 3
    keys = {(s["source"], s["name"]) for s in data["series"]}
    assert keys == {("a", "x"), ("a", "y"), ("b", "x")}


def test_summary_filter_by_source(client):
    client.post("/api/metrics", json={"source": "a", "name": "n", "value": 1})
    client.post("/api/metrics", json={"source": "b", "name": "n", "value": 2})
    data = client.get("/api/metrics/summary?source=a").get_json()
    assert data["total_metrics"] == 1
    assert len(data["series"]) == 1
    assert data["series"][0]["source"] == "a"


def test_summary_invalid_since(client):
    resp = client.get("/api/metrics/summary?since=notanumber")
    assert resp.status_code == 400


def test_summary_until_before_since(client):
    resp = client.get("/api/metrics/summary?since=200&until=100")
    assert resp.status_code == 400


def test_batch_all_accepted(client):
    resp = client.post("/api/metrics/batch", json={
        "metrics": [
            {"source": "a", "name": "cpu", "value": 1.0, "timestamp": 100.0},
            {"source": "b", "name": "mem", "value": 2.0, "timestamp": 200.0},
            {"source": "c", "name": "disk", "value": 3.0},
        ],
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["total"] == 3
    assert data["accepted_count"] == 3
    assert data["rejected_count"] == 0
    assert len(data["accepted"]) == 3
    assert data["rejected"] == []

    list_resp = client.get("/api/metrics")
    assert list_resp.get_json()["total"] == 3


def test_batch_partial_failure_returns_207(client):
    resp = client.post("/api/metrics/batch", json={
        "metrics": [
            {"source": "ok", "name": "cpu", "value": 1.0},
            {"source": "", "name": "cpu", "value": 1.0},
            {"source": "ok", "name": "cpu", "value": "not-a-number"},
            {"source": "ok2", "name": "mem", "value": 2.0},
        ],
    })
    assert resp.status_code == 207
    data = resp.get_json()
    assert data["total"] == 4
    assert data["accepted_count"] == 2
    assert data["rejected_count"] == 2
    indices = sorted([r["index"] for r in data["rejected"]])
    assert indices == [1, 2]
    assert "source" in data["rejected"][0]["error"].lower()

    list_resp = client.get("/api/metrics")
    assert list_resp.get_json()["total"] == 2


def test_batch_all_rejected_returns_400(client):
    resp = client.post("/api/metrics/batch", json={
        "metrics": [
            {"source": "", "name": "cpu", "value": 1.0},
            {"source": "ok", "name": "", "value": 1.0},
        ],
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["accepted_count"] == 0
    assert data["rejected_count"] == 2


def test_batch_rejects_non_object_body(client):
    resp = client.post("/api/metrics/batch", json=[])
    assert resp.status_code == 400


def test_batch_rejects_missing_metrics_field(client):
    resp = client.post("/api/metrics/batch", json={})
    assert resp.status_code == 400
    assert "metrics" in resp.get_json()["error"].lower()


def test_batch_rejects_non_array_metrics(client):
    resp = client.post("/api/metrics/batch", json={"metrics": "not-an-array"})
    assert resp.status_code == 400


def test_batch_rejects_empty_array(client):
    resp = client.post("/api/metrics/batch", json={"metrics": []})
    assert resp.status_code == 400
    assert "empty" in resp.get_json()["error"].lower()


def test_batch_rejects_over_max_size(client, monkeypatch):
    monkeypatch.setattr("main.BATCH_MAX_SIZE", 3)
    resp = client.post("/api/metrics/batch", json={
        "metrics": [{"source": "a", "name": "n", "value": 1.0}] * 4,
    })
    assert resp.status_code == 400
    assert "at most 3" in resp.get_json()["error"]


def test_batch_non_object_item_rejected_with_index(client):
    resp = client.post("/api/metrics/batch", json={
        "metrics": [
            {"source": "ok", "name": "cpu", "value": 1.0},
            "this is not an object",
            42,
        ],
    })
    assert resp.status_code == 207
    data = resp.get_json()
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 2
    rejected_indices = sorted([r["index"] for r in data["rejected"]])
    assert rejected_indices == [1, 2]


def test_batch_assigns_default_timestamp(client):
    resp = client.post("/api/metrics/batch", json={
        "metrics": [{"source": "a", "name": "n", "value": 1.0}],
    })
    assert resp.status_code == 201
    accepted = resp.get_json()["accepted"]
    assert accepted[0]["timestamp"] > 0


def test_batch_records_visible_in_summary(client):
    client.post("/api/metrics/batch", json={
        "metrics": [
            {"source": "svc", "name": "cpu", "value": 10.0},
            {"source": "svc", "name": "cpu", "value": 20.0},
            {"source": "svc", "name": "cpu", "value": 30.0},
        ],
    })
    data = client.get("/api/metrics/summary").get_json()
    assert data["total_metrics"] == 3
    s = data["series"][0]
    assert s["count"] == 3
    assert s["min"] == 10.0
    assert s["max"] == 30.0
    assert s["avg"] == 20.0
