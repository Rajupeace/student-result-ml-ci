import logging
import math
import os
import sys
import time
import uuid
from pathlib import Path
from numbers import Real

import joblib
import pandas as pd
from flask import Flask, Response, g, jsonify, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from werkzeug.exceptions import HTTPException


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("student_result_api")

app = Flask(__name__)

MODEL_PATH = Path("student_result_model.pkl")
FEATURES = [
    "attendance",
    "internal_marks",
    "assignment_marks",
    "previous_score",
]

METRICS_REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "student_api_http_requests_total",
    "Total HTTP requests received by the Student Result Prediction API",
    ["method", "path", "status"],
    registry=METRICS_REGISTRY,
)
HTTP_LATENCY = Histogram(
    "student_api_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    registry=METRICS_REGISTRY,
)
PREDICTIONS = Counter(
    "student_api_predictions_total",
    "Student Result Prediction inference attempts",
    ["result"],
    registry=METRICS_REGISTRY,
)
MODEL_LOADED = Gauge(
    "student_api_model_loaded",
    "Whether the Student Result Prediction model is loaded",
    registry=METRICS_REGISTRY,
)


def load_model():
    """Load the model once, logging startup and error events without input data."""
    try:
        loaded_model = joblib.load(MODEL_PATH)
    except Exception:
        MODEL_LOADED.set(0)
        logger.exception("event=model_load_failed model_file=%s", MODEL_PATH.name)
        raise
    MODEL_LOADED.set(1)
    logger.info("event=model_loaded model_file=%s", MODEL_PATH.name)
    return loaded_model


try:
    model = load_model()
except Exception:
    # Keep the process alive so health/metrics and runtime diagnostics are available.
    # Prediction requests will retry loading and return a logged server error.
    model = None


@app.before_request
def start_request_tracking():
    g.request_id = uuid.uuid4().hex
    g.request_started_at = time.perf_counter()


@app.after_request
def log_and_measure_request(response):
    request_id = getattr(g, "request_id", "unknown")
    duration = time.perf_counter() - getattr(g, "request_started_at", time.perf_counter())
    path = request.url_rule.rule if request.url_rule else "/unmatched"
    method = request.method

    if request.path != "/metrics":
        HTTP_REQUESTS.labels(method=method, path=path, status=str(response.status_code)).inc()
        HTTP_LATENCY.labels(method=method, path=path).observe(duration)

    response.headers["X-Request-ID"] = request_id
    log_method = logger.warning if response.status_code >= 400 else logger.info
    log_method(
        "event=http_request method=%s path=%s status=%s duration_ms=%.3f request_id=%s",
        method,
        path,
        response.status_code,
        duration * 1000,
        request_id,
    )
    return response


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        return error
    logger.exception(
        "event=%s request_id=%s error_type=%s",
        "prediction_failed" if request.path == "/predict" else "unhandled_exception",
        getattr(g, "request_id", "unknown"),
        type(error).__name__,
    )
    return jsonify({"error": "Internal server error"}), 500


@app.get("/")
def health_check():
    return jsonify({
        "status": "ok",
        "service": "student-result-prediction",
    })


@app.get("/health")
def health_endpoint():
    return jsonify({"status": "healthy"})


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(METRICS_REGISTRY), content_type=CONTENT_TYPE_LATEST)


@app.post("/predict")
def predict():
    global model

    data = request.get_json(silent=True)
    if not data:
        logger.warning(
            "event=validation_error reason=json_body_required request_id=%s",
            g.request_id,
        )
        return jsonify({"error": "JSON request body is required"}), 400

    missing_fields = [feature for feature in FEATURES if feature not in data]
    if missing_fields:
        # Log only schema field names; never log submitted values or identifiers.
        logger.warning(
            "event=validation_error missing_fields=%s request_id=%s",
            ",".join(missing_fields),
            g.request_id,
        )
        return jsonify({
            "error": "Missing required fields",
            "missing_fields": missing_fields,
        }), 400

    invalid_fields = [
        feature
        for feature in FEATURES
        if isinstance(data[feature], bool)
        or not isinstance(data[feature], Real)
        or not math.isfinite(float(data[feature]))
    ]
    if invalid_fields:
        logger.warning(
            "event=validation_error invalid_fields=%s request_id=%s",
            ",".join(invalid_fields),
            g.request_id,
        )
        return jsonify({
            "error": "Numeric values are required",
            "invalid_fields": invalid_fields,
        }), 400

    try:
        sample = pd.DataFrame([{feature: data[feature] for feature in FEATURES}])
        if model is None:
            model = load_model()
        prediction_code = int(model.predict(sample)[0])
    except Exception:
        PREDICTIONS.labels(result="error").inc()
        raise

    PREDICTIONS.labels(result="success").inc()
    prediction = "PASS" if prediction_code == 1 else "FAIL"
    logger.info(
        "event=prediction_succeeded prediction=%s request_id=%s",
        prediction,
        g.request_id,
    )
    return jsonify({
        "prediction": prediction,
        "prediction_code": prediction_code,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
