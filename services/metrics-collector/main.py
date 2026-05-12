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


@app.route("/api/metrics", methods=["POST"])
def post_metric():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _reject("Request body must be a JSON object")

    source = data.get("source")
    name = data.get("name")
    value = data.get("value")

    if not isinstance(source, str):
        return _reject("Field 'source' must be a string")
    source = source.strip()
    if not source:
        return _reject("Field 'source' must not be blank")
    if len(source) > MAX_SOURCE_LENGTH:
        return _reject(
            f"Field 'source' must be at most {MAX_SOURCE_LENGTH} characters",
        )

    if not isinstance(name, str):
        return _reject("Field 'name' must be a string")
    name = name.strip()
    if not name:
        return _reject("Field 'name' must not be blank")
    if len(name) > MAX_NAME_LENGTH:
        return _reject(
            f"Field 'name' must be at most {MAX_NAME_LENGTH} characters",
        )

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _reject("Field 'value' must be a number")
    if not math.isfinite(float(value)):
        return _reject("Field 'value' must be a finite number")
    if abs(float(value)) > MAX_VALUE:
        return _reject(f"Field 'value' must be within ±{MAX_VALUE}")

    timestamp = data.get("timestamp")
    if timestamp is None:
        timestamp = time.time()
    else:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return _reject("Field 'timestamp' must be a number")
        if not math.isfinite(float(timestamp)) or float(timestamp) < 0:
            return _reject("Field 'timestamp' must be a non-negative finite number")
        timestamp = float(timestamp)

    record = {
        "source": source,
        "name": name,
        "value": float(value),
        "timestamp": timestamp,
    }
    store.add(record)
    logger.info(
        "Recorded metric source=%s name=%s value=%s",
        source, name, record["value"],
    )
    return jsonify(record), 201


@app.route("/api/metrics", methods=["GET"])
def list_metrics():
    items = store.snapshot()
    return jsonify({"total": len(items), "metrics": items})


if __name__ == "__main__":  # pragma: no cover
    logger.info("Starting metrics-collector on port %d", PORT)
    app.run(host="0.0.0.0", port=PORT)
