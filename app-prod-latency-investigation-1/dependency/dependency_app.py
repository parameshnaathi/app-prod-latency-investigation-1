import os
import socket
import time

from flask import Flask, jsonify, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

POD_NAME = os.getenv("HOSTNAME", socket.gethostname())

DEPENDENCY_REQUESTS = Counter(
    "dependency_requests_total",
    "Total dependency requests",
    ["status"],
)

DEPENDENCY_DURATION = Histogram(
    "dependency_request_duration_seconds",
    "Dependency request duration",
    buckets=(
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "dependency",
            "pod": POD_NAME,
        }
    ), 200


@app.route("/work", methods=["GET"])
def work():
    start = time.monotonic()

    try:
        # Healthy baseline dependency latency.
        time.sleep(0.03)

        DEPENDENCY_REQUESTS.labels(status="success").inc()

        return jsonify(
            {
                "status": "success",
                "service": "dependency",
                "pod": POD_NAME,
            }
        ), 200

    except Exception as exc:
        DEPENDENCY_REQUESTS.labels(status="error").inc()

        return jsonify(
            {
                "status": "error",
                "error": str(exc),
                "pod": POD_NAME,
            }
        ), 500

    finally:
        DEPENDENCY_DURATION.observe(time.monotonic() - start)


@app.route("/metrics", methods=["GET"])
def metrics():
    return Response(
        generate_latest(),
        mimetype=CONTENT_TYPE_LATEST,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081)