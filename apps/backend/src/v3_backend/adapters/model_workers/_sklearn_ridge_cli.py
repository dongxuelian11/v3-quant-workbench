from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
from collections.abc import Mapping
from typing import Any


PROTOCOL_VERSION = "v3.model-worker/2"
BACKEND_NAME = "scikit-learn-ridge"
THREAD_KEYS = (
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
)


def _strict(payload: object, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError(f"{name} keys must be exactly {sorted(expected)}")
    return payload


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _request_id(value: object, prefix: str, name: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{name} must be a parent-issued request ID")
    return value


def _runtime_payload() -> dict[str, object]:
    packages = tuple(
        sorted(
            (name, importlib.metadata.version(name))
            for name in (
                "joblib",
                "narwhals",
                "numpy",
                "scikit-learn",
                "scipy",
                "threadpoolctl",
            )
        )
    )
    limits = tuple(sorted((key, os.environ.get(key, "")) for key in THREAD_KEYS))
    descriptor = {
        "backend_name": BACKEND_NAME,
        "backend_version": dict(packages)["scikit-learn"],
        "protocol_version": PROTOCOL_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "packages": [list(item) for item in packages],
        "thread_limits": [list(item) for item in limits],
    }
    encoded = json.dumps(
        descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        **descriptor,
        "fingerprint": "mrt_sha256_" + hashlib.sha256(encoded).hexdigest(),
    }


def _rows(payload: object, feature_count: int, name: str) -> tuple[list[str], list[list[float]], list[float]]:
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{name} must be a non-empty array")
    sample_ids: list[str] = []
    features: list[list[float]] = []
    labels: list[float] = []
    for value in payload:
        row = _strict(value, {"sample_id", "features", "label"}, name)
        sample_id = row["sample_id"]
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError(f"{name} sample_id must be non-empty")
        row_features = row["features"]
        if not isinstance(row_features, list) or len(row_features) != feature_count:
            raise ValueError(f"{name} feature count mismatch")
        sample_ids.append(sample_id)
        features.append(
            [_finite(item, f"{name} feature") for item in row_features]
        )
        labels.append(_finite(row["label"], f"{name} label"))
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError(f"{name} sample IDs must be unique")
    return sample_ids, features, labels


def _rmse(expected: list[float], observed: list[float]) -> float:
    return math.sqrt(
        math.fsum((left - right) ** 2 for left, right in zip(expected, observed, strict=True))
        / len(expected)
    )


def _train(request: Mapping[str, Any]) -> dict[str, object]:
    from sklearn.linear_model import Ridge

    request_id = _request_id(
        request["model_training_request_id"],
        "mtr_sha256_",
        "model_training_request_id",
    )
    spec = _strict(
        request["spec"],
        {"alpha", "fit_intercept", "solver", "feature_order", "seed"},
        "training spec",
    )
    if spec["solver"] != "svd":
        raise ValueError("V0 worker admits only solver=svd")
    if not isinstance(spec["fit_intercept"], bool):
        raise TypeError("fit_intercept must be bool")
    if not isinstance(spec["seed"], int) or isinstance(spec["seed"], bool) or spec["seed"] < 0:
        raise ValueError("seed must be a non-negative integer")
    feature_order = spec["feature_order"]
    if (
        not isinstance(feature_order, list)
        or not feature_order
        or any(not isinstance(value, str) or not value for value in feature_order)
    ):
        raise ValueError("feature_order must be non-empty strings")
    train_ids, train_x, train_y = _rows(
        request["train_rows"], len(feature_order), "train_rows"
    )
    validation_ids, validation_x, validation_y = _rows(
        request["validation_rows"], len(feature_order), "validation_rows"
    )
    model = Ridge(
        alpha=_finite(spec["alpha"], "alpha"),
        fit_intercept=spec["fit_intercept"],
        solver="svd",
    )
    model.fit(train_x, train_y)
    train_predictions = [float(value) for value in model.predict(train_x)]
    validation_predictions = [float(value) for value in model.predict(validation_x)]
    return {
        "model_training_request_id": request_id,
        "runtime": _runtime_payload(),
        "feature_order": feature_order,
        "coefficients": [_finite(value, "coefficient") for value in model.coef_],
        "intercept": _finite(model.intercept_, "intercept"),
        "train_sample_ids": train_ids,
        "validation_sample_ids": validation_ids,
        "train_rmse": _rmse(train_y, train_predictions),
        "validation_rmse": _rmse(validation_y, validation_predictions),
        "seed": spec["seed"],
    }


def _predict(request: Mapping[str, Any]) -> dict[str, object]:
    request_id = _request_id(
        request["model_prediction_request_id"],
        "mpr_sha256_",
        "model_prediction_request_id",
    )
    feature_order = request["feature_order"]
    coefficients = request["coefficients"]
    if not isinstance(feature_order, list) or not isinstance(coefficients, list):
        raise ValueError("feature_order and coefficients must be arrays")
    if len(feature_order) != len(coefficients) or not feature_order:
        raise ValueError("feature_order and coefficient count must match")
    coefficient_values = [_finite(value, "coefficient") for value in coefficients]
    intercept = _finite(request["intercept"], "intercept")
    rows = request["rows"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("prediction rows must be non-empty")
    predictions: list[dict[str, object]] = []
    for value in rows:
        row = _strict(value, {"sample_id", "features"}, "prediction row")
        sample_id = row["sample_id"]
        features = row["features"]
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError("prediction sample_id must be non-empty")
        if not isinstance(features, list) or len(features) != len(coefficient_values):
            raise ValueError("prediction feature count mismatch")
        numeric_features = [_finite(item, "prediction feature") for item in features]
        prediction = math.fsum(
            coefficient * feature
            for coefficient, feature in zip(
                coefficient_values, numeric_features, strict=True
            )
        ) + intercept
        predictions.append(
            {"sample_id": sample_id, "value": _finite(prediction, "prediction")}
        )
    return {
        "model_prediction_request_id": request_id,
        "runtime": _runtime_payload(),
        "feature_order": feature_order,
        "predictions": predictions,
    }


def handle(payload: object) -> dict[str, object]:
    request = _strict(
        payload,
        {"operation", "protocol_version", "payload"},
        "worker request",
    )
    if request["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("worker protocol version mismatch")
    operation = request["operation"]
    if operation == "describe":
        _strict(request["payload"], set(), "describe payload")
        return _runtime_payload()
    if operation == "train_ridge":
        body = _strict(
            request["payload"],
            {
                "model_training_request_id",
                "spec",
                "train_rows",
                "validation_rows",
            },
            "train payload",
        )
        return _train(body)
    if operation == "predict_linear":
        body = _strict(
            request["payload"],
            {
                "model_prediction_request_id",
                "feature_order",
                "coefficients",
                "intercept",
                "rows",
            },
            "predict payload",
        )
        return _predict(body)
    raise ValueError("unsupported worker operation")


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
        if not raw:
            raise ValueError("worker request is empty")
        request = json.loads(raw.decode("utf-8"))
        response = handle(request)
        sys.stdout.write(
            json.dumps(
                response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        return 0
    except Exception as error:  # worker boundary converts every failure explicitly
        sys.stderr.write(
            json.dumps(
                {"error_code": "MODEL_WORKER_FAILURE", "message": str(error)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
