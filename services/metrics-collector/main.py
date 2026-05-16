"""SyncPulse metrics-collector service.

外部メトリクス源から受信したメトリクスを内部ストアに溜め、
後段の transformer / dashboard-api に転送するためのエントリポイント。
本ファイルは初期実装（最小構成）であり、/health と /api/metrics のみを提供する。
"""

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field

from flask import Flask, jsonify, request


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("metrics-collector")

PORT = int(os.environ.get("METRICS_COLLECTOR_PORT", "8000"))
MAX_METRICS = int(os.environ.get("MAX_METRICS", "10000"))
MAX_SOURCE_LENGTH = int(os.environ.get("MAX_SOURCE_LENGTH", "200"))
MAX_NAME_LENGTH = int(os.environ.get("MAX_NAME_LENGTH", "200"))
MAX_VALUE = float(os.environ.get("MAX_VALUE", "1e12"))
LIST_DEFAULT_LIMIT = max(1, int(os.environ.get("LIST_DEFAULT_LIMIT", "100")))
LIST_MAX_LIMIT = max(LIST_DEFAULT_LIMIT, int(os.environ.get("LIST_MAX_LIMIT", "1000")))
BATCH_MAX_SIZE = max(1, int(os.environ.get("BATCH_MAX_SIZE", "1000")))
ALLOWED_SORT_FIELDS = {"timestamp", "source", "name", "value"}
ALLOWED_SORT_ORDERS = {"asc", "desc"}
ALLOWED_SOURCES_SORT_FIELDS = {
    "source", "total_metrics", "first_seen", "last_seen", "metric_names",
}


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


app = Flask(__name__)


@dataclass
class MetricsStore:
    items: list[dict] = field(default_factory=list)
    max_items: int = MAX_METRICS
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, item: dict) -> dict:
        with self._lock:
            self.items.append(item)
            if len(self.items) > self.max_items:
                removed = len(self.items) - self.max_items
                del self.items[:removed]
                logger.info(
                    "Evicted %d old metrics (store capped at %d)",
                    removed, self.max_items,
                )
        return item

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.items)

    def delete_by_source(self, source: str) -> int:
        with self._lock:
            before = len(self.items)
            self.items = [m for m in self.items if m.get("source") != source]
            deleted = before - len(self.items)
        if deleted > 0:
            logger.info("Deleted %d metrics for source=%s", deleted, source)
        return deleted

    def delete_by_filter(
        self,
        source: str | None = None,
        name: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> int:
        def matches(m: dict) -> bool:
            if source is not None and m.get("source") != source:
                return False
            if name is not None and m.get("name") != name:
                return False
            ts = m.get("timestamp", 0)
            if since is not None and ts < since:
                return False
            if until is not None and ts > until:
                return False
            return True

        with self._lock:
            before = len(self.items)
            self.items = [m for m in self.items if not matches(m)]
            deleted = before - len(self.items)
        if deleted > 0:
            logger.info(
                "Deleted %d metrics (source=%s name=%s since=%s until=%s)",
                deleted, source, name, since, until,
            )
        return deleted


store = MetricsStore()
start_time = time.time()


@app.route("/health", methods=["GET"])
def health():
    uptime = time.time() - start_time
    return jsonify({
        "status": "ok",
        "service": "metrics-collector",
        "uptime_seconds": round(uptime, 2),
    })


def _reject(msg: str, status: int = 400):
    return jsonify({"error": msg}), status


def _validate_metric(data: dict) -> tuple[dict | None, str | None]:
    """Validate a single metric payload. Returns (record, error_message)."""
    if not isinstance(data, dict):
        return None, "Metric must be a JSON object"

    source = data.get("source")
    name = data.get("name")
    value = data.get("value")

    if not isinstance(source, str):
        return None, "Field 'source' must be a string"
    source = source.strip()
    if not source:
        return None, "Field 'source' must not be blank"
    if len(source) > MAX_SOURCE_LENGTH:
        return None, f"Field 'source' must be at most {MAX_SOURCE_LENGTH} characters"

    if not isinstance(name, str):
        return None, "Field 'name' must be a string"
    name = name.strip()
    if not name:
        return None, "Field 'name' must not be blank"
    if len(name) > MAX_NAME_LENGTH:
        return None, f"Field 'name' must be at most {MAX_NAME_LENGTH} characters"

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "Field 'value' must be a number"
    if not math.isfinite(float(value)):
        return None, "Field 'value' must be a finite number"
    if abs(float(value)) > MAX_VALUE:
        return None, f"Field 'value' must be within ±{MAX_VALUE}"

    timestamp = data.get("timestamp")
    if timestamp is None:
        timestamp = time.time()
    else:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return None, "Field 'timestamp' must be a number"
        if not math.isfinite(float(timestamp)) or float(timestamp) < 0:
            return None, "Field 'timestamp' must be a non-negative finite number"
        timestamp = float(timestamp)

    return {
        "source": source,
        "name": name,
        "value": float(value),
        "timestamp": timestamp,
    }, None


@app.route("/api/metrics", methods=["POST"])
def post_metric():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _reject("Request body must be a JSON object")

    record, err = _validate_metric(data)
    if err is not None:
        return _reject(err)

    store.add(record)
    logger.info(
        "Recorded metric source=%s name=%s value=%s",
        record["source"], record["name"], record["value"],
    )
    return jsonify(record), 201


@app.route("/api/metrics/batch", methods=["POST"])
def post_metrics_batch():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _reject("Request body must be a JSON object")
    metrics = data.get("metrics")
    if not isinstance(metrics, list):
        return _reject("Field 'metrics' must be an array")
    if len(metrics) == 0:
        return _reject("Field 'metrics' must not be empty")
    if len(metrics) > BATCH_MAX_SIZE:
        return _reject(
            f"Field 'metrics' must contain at most {BATCH_MAX_SIZE} items",
        )

    accepted: list[dict] = []
    rejected: list[dict] = []
    for index, item in enumerate(metrics):
        record, err = _validate_metric(item)
        if err is not None:
            rejected.append({"index": index, "error": err})
        else:
            accepted.append(record)

    for record in accepted:
        store.add(record)

    total = len(metrics)
    if len(rejected) == total:
        status = 400
    elif rejected:
        status = 207  # Multi-Status: partial success
    else:
        status = 201

    logger.info(
        "Batch ingest: total=%d accepted=%d rejected=%d",
        total, len(accepted), len(rejected),
    )
    return jsonify({
        "total": total,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
    }), status


def _parse_timestamp_arg(value: str, name: str) -> float:
    try:
        ts = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Query parameter '{name}' must be a number") from e
    if not math.isfinite(ts):
        raise ValueError(f"Query parameter '{name}' must be a finite number")
    if ts < 0:
        raise ValueError(f"Query parameter '{name}' must be non-negative")
    return ts


def _filter_metrics(
    items: list[dict],
    source: str | None,
    name: str | None,
    since: float | None,
    until: float | None,
) -> list[dict]:
    filtered = items
    if source:
        filtered = [m for m in filtered if m.get("source") == source]
    if name:
        filtered = [m for m in filtered if m.get("name") == name]
    if since is not None:
        filtered = [m for m in filtered if m.get("timestamp", 0) >= since]
    if until is not None:
        filtered = [m for m in filtered if m.get("timestamp", 0) <= until]
    return filtered


@app.route("/api/metrics", methods=["GET"])
def list_metrics():
    source = request.args.get("source")
    name = request.args.get("name")
    sort_field = request.args.get("sort", "timestamp")
    sort_order = request.args.get("order", "asc")

    if sort_field not in ALLOWED_SORT_FIELDS:
        return _reject(
            "Query parameter 'sort' must be one of: "
            + ", ".join(sorted(ALLOWED_SORT_FIELDS)),
        )
    if sort_order not in ALLOWED_SORT_ORDERS:
        return _reject(
            "Query parameter 'order' must be one of: "
            + ", ".join(sorted(ALLOWED_SORT_ORDERS)),
        )

    try:
        since = _parse_timestamp_arg(request.args["since"], "since") \
            if "since" in request.args else None
        until = _parse_timestamp_arg(request.args["until"], "until") \
            if "until" in request.args else None
    except ValueError as e:
        return _reject(str(e))

    if since is not None and until is not None and since > until:
        return _reject("Query parameter 'until' must be greater than or equal to 'since'")

    limit_raw = request.args.get("limit")
    if limit_raw is None:
        limit = LIST_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            return _reject("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > LIST_MAX_LIMIT:
            return _reject(f"Query parameter 'limit' must be between 1 and {LIST_MAX_LIMIT}")

    offset_raw = request.args.get("offset")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            return _reject("Query parameter 'offset' must be an integer")
        if offset < 0:
            return _reject("Query parameter 'offset' must be non-negative")

    items = store.snapshot()
    filtered = _filter_metrics(items, source, name, since, until)

    reverse = sort_order == "desc"
    filtered.sort(key=lambda m: m.get(sort_field, ""), reverse=reverse)

    total = len(filtered)
    page = filtered[offset:offset + limit]
    return jsonify({
        "total": total,
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "sort": sort_field,
        "order": sort_order,
        "metrics": page,
    })


@app.route("/api/metrics", methods=["DELETE"])
def delete_metrics():
    source = request.args.get("source")
    name = request.args.get("name")
    since_raw = request.args.get("since")
    until_raw = request.args.get("until")

    if source is not None:
        source = source.strip()
        if not source:
            return _reject("Query parameter 'source' must not be blank")
    if name is not None:
        name = name.strip()
        if not name:
            return _reject("Query parameter 'name' must not be blank")

    if not any([source, name, since_raw, until_raw]):
        return _reject(
            "At least one of 'source', 'name', 'since', 'until' is required",
        )

    try:
        since = _parse_timestamp_arg(since_raw, "since") if since_raw is not None else None
        until = _parse_timestamp_arg(until_raw, "until") if until_raw is not None else None
    except ValueError as e:
        return _reject(str(e))

    if since is not None and until is not None and since > until:
        return _reject("Query parameter 'until' must be greater than or equal to 'since'")

    deleted = store.delete_by_filter(
        source=source, name=name, since=since, until=until,
    )
    if deleted == 0:
        return jsonify({
            "error": "No metrics found for the specified filters",
            "deleted_count": 0,
        }), 404

    response: dict = {"message": "Metrics deleted", "deleted_count": deleted}
    if source is not None:
        response["source"] = source
    if name is not None:
        response["name"] = name
    if since is not None:
        response["since"] = since
    if until is not None:
        response["until"] = until
    return jsonify(response)


@app.route("/api/metrics/sources", methods=["GET"])
def list_sources():
    """Aggregate metrics by source (host / origin)."""
    name = request.args.get("name")
    sort_field = request.args.get("sort", "source")
    sort_order = request.args.get("order", "asc")

    if sort_field not in ALLOWED_SOURCES_SORT_FIELDS:
        return _reject(
            "Query parameter 'sort' must be one of: "
            + ", ".join(sorted(ALLOWED_SOURCES_SORT_FIELDS)),
        )
    if sort_order not in ALLOWED_SORT_ORDERS:
        return _reject(
            "Query parameter 'order' must be one of: "
            + ", ".join(sorted(ALLOWED_SORT_ORDERS)),
        )

    try:
        since = _parse_timestamp_arg(request.args["since"], "since") \
            if "since" in request.args else None
        until = _parse_timestamp_arg(request.args["until"], "until") \
            if "until" in request.args else None
    except ValueError as e:
        return _reject(str(e))

    if since is not None and until is not None and since > until:
        return _reject("Query parameter 'until' must be greater than or equal to 'since'")

    limit_raw = request.args.get("limit")
    if limit_raw is None:
        limit = LIST_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            return _reject("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > LIST_MAX_LIMIT:
            return _reject(f"Query parameter 'limit' must be between 1 and {LIST_MAX_LIMIT}")

    offset_raw = request.args.get("offset")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            return _reject("Query parameter 'offset' must be an integer")
        if offset < 0:
            return _reject("Query parameter 'offset' must be non-negative")

    items = store.snapshot()
    filtered = _filter_metrics(items, None, name, since, until)

    by_source: dict[str, dict] = {}
    for m in filtered:
        src = m.get("source")
        if src is None:
            continue
        entry = by_source.get(src)
        if entry is None:
            by_source[src] = {
                "source": src,
                "total_metrics": 1,
                "first_seen": m.get("timestamp", 0.0),
                "last_seen": m.get("timestamp", 0.0),
                "metric_names_set": {m.get("name")} if m.get("name") else set(),
            }
            continue
        entry["total_metrics"] += 1
        ts = m.get("timestamp", 0.0)
        if ts < entry["first_seen"]:
            entry["first_seen"] = ts
        if ts > entry["last_seen"]:
            entry["last_seen"] = ts
        if m.get("name"):
            entry["metric_names_set"].add(m.get("name"))

    sources = []
    for entry in by_source.values():
        names_set = entry.pop("metric_names_set", set())
        entry["metric_names"] = sorted(names_set)
        sources.append(entry)

    reverse = sort_order == "desc"
    if sort_field == "metric_names":
        sources.sort(key=lambda s: len(s["metric_names"]), reverse=reverse)
    else:
        sources.sort(key=lambda s: s.get(sort_field, ""), reverse=reverse)

    total = len(sources)
    page = sources[offset:offset + limit]
    return jsonify({
        "total": total,
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "sort": sort_field,
        "order": sort_order,
        "sources": page,
    })


@app.route("/api/metrics/summary", methods=["GET"])
def metrics_summary():
    source = request.args.get("source")
    name = request.args.get("name")

    try:
        since = _parse_timestamp_arg(request.args["since"], "since") \
            if "since" in request.args else None
        until = _parse_timestamp_arg(request.args["until"], "until") \
            if "until" in request.args else None
    except ValueError as e:
        return _reject(str(e))

    if since is not None and until is not None and since > until:
        return _reject("Query parameter 'until' must be greater than or equal to 'since'")

    items = store.snapshot()
    filtered = _filter_metrics(items, source, name, since, until)

    groups: dict[tuple, list[float]] = {}
    for m in filtered:
        key = (m.get("source"), m.get("name"))
        groups.setdefault(key, []).append(float(m.get("value", 0.0)))

    series = []
    for (src, nm), values in groups.items():
        sorted_v = sorted(values)
        n = len(sorted_v)
        series.append({
            "source": src,
            "name": nm,
            "count": n,
            "min": round(sorted_v[0], 6) if sorted_v else 0.0,
            "max": round(sorted_v[-1], 6) if sorted_v else 0.0,
            "avg": round(sum(sorted_v) / n, 6) if n else 0.0,
            "p50": round(_percentile(sorted_v, 50), 6),
            "p95": round(_percentile(sorted_v, 95), 6),
            "p99": round(_percentile(sorted_v, 99), 6),
        })

    series.sort(key=lambda s: (s["source"] or "", s["name"] or ""))
    return jsonify({"total_metrics": len(filtered), "series": series})


if __name__ == "__main__":  # pragma: no cover
    logger.info("Starting metrics-collector on port %d", PORT)
    app.run(host="0.0.0.0", port=PORT)
