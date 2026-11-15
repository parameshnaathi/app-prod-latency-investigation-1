import os
import socket
import time
import requests

from flask import Flask, jsonify, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

POD_NAME = os.getenv("HOSTNAME", socket.gethostname())

DEPENDENCY_URL = os.getenv(
    "DEPENDENCY_URL",
    "http://dependency/work"
)

# Total number of checkout requests.
CHECKOUT_REQUESTS = Counter(
    "checkout_requests_total",
    "Total number of requests received by the checkout endpoint",
    ["status"]
)

# Request latency histogram.
# Later we will calculate p50, p95 and p99 from these buckets.
CHECKOUT_DURATION = Histogram(
    "checkout_request_duration_seconds",
    "Checkout request duration in seconds",
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

DEPENDENCY_CALLS = Counter(
    "checkout_dependency_requests_total",
    "Total requests from checkout to dependency",
    ["status"]
)

DEPENDENCY_DURATION = Histogram(
    "checkout_dependency_duration_seconds",
    "Duration of dependency calls from checkout",
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
    """
    Liveness-style endpoint.

    This checks whether the Checkout application itself is alive.
    It intentionally does not depend on downstream services.
    """
    return jsonify(
        {
            "status": "ok",
            "service": "checkout",
            "pod": POD_NAME,
        }
    ), 200


@app.route("/checkout", methods=["GET"])
def checkout():

    request_start = time.monotonic()

    try:

        dependency_start = time.monotonic()

        try:

            dependency_response = requests.get(
                DEPENDENCY_URL,
                timeout=3
            )

            dependency_response.raise_for_status()

            DEPENDENCY_CALLS.labels(
                status="success"
            ).inc()

        except requests.RequestException as exc:

            DEPENDENCY_CALLS.labels(
                status="error"
            ).inc()

            app.logger.exception(
                "Dependency request failed"
            )

            CHECKOUT_REQUESTS.labels(
                status="error"
            ).inc()

            return jsonify(
                {
                    "status": "error",
                    "service": "checkout",
                    "dependency": "failed",
                    "error": str(exc),
                    "pod": POD_NAME,
                }
            ), 503

        finally:

            DEPENDENCY_DURATION.observe(
                time.monotonic() - dependency_start
            )

        dependency_data = dependency_response.json()

        CHECKOUT_REQUESTS.labels(
            status="success"
        ).inc()

        return jsonify(
            {
                "status": "success",
                "service": "checkout",
                "pod": POD_NAME,
                "dependency": dependency_data,
            }
        ), 200

    finally:

        CHECKOUT_DURATION.observe(
            time.monotonic() - request_start
        )


@app.route("/metrics", methods=["GET"])
def metrics():
    """
    Prometheus-compatible metrics endpoint.
    """
    return Response(
        generate_latest(),
        mimetype=CONTENT_TYPE_LATEST,
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
    )