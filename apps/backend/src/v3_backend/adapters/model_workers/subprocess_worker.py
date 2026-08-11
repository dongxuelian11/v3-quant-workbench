from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from v3_backend.domain.models import (
    PredictionDatasetView,
    SafeLinearModelArtifact,
    TrainingDatasetView,
    TrainingSpecVersion,
    WorkerPredictionCandidate,
    WorkerRuntimeFingerprint,
    WorkerTrainingCandidate,
)
from v3_backend.workers.entrypoint import WorkerSandboxPolicy


MODEL_WORKER_PROTOCOL_VERSION = "v3.model-worker/1"


class ModelWorkerError(RuntimeError):
    pass


class SklearnRidgeSubprocessWorker:
    def __init__(
        self,
        *,
        python_executable: str | None = None,
        expected_backend_version: str = "1.9.0",
        timeout_seconds: float = 30.0,
        script_path: Path | None = None,
    ) -> None:
        self._python_executable = python_executable or sys.executable
        self._expected_backend_version = expected_backend_version
        self._timeout_seconds = timeout_seconds
        self._script_path = script_path or Path(__file__).with_name(
            "_sklearn_ridge_cli.py"
        )
        self._sandbox_policy = WorkerSandboxPolicy(
            allowed_environment_keys=frozenset(
                {
                    "APPDATA",
                    "LOCALAPPDATA",
                    "PATH",
                    "PYTHONUTF8",
                    "SystemRoot",
                    "TEMP",
                    "TMP",
                    "USERPROFILE",
                    "WINDIR",
                }
            )
        )
        self._runtime: WorkerRuntimeFingerprint | None = None

    @property
    def runtime(self) -> WorkerRuntimeFingerprint:
        if self._runtime is None:
            runtime = WorkerRuntimeFingerprint.from_wire(
                self._invoke("describe", {})
            )
            if runtime.backend_name != "scikit-learn-ridge":
                raise ModelWorkerError("unexpected model worker backend")
            if runtime.backend_version != self._expected_backend_version:
                raise ModelWorkerError(
                    "model worker version mismatch: expected "
                    f"{self._expected_backend_version}, observed {runtime.backend_version}"
                )
            self._runtime = runtime
        return self._runtime

    def sanitized_environment(
        self, inherited: Mapping[str, str]
    ) -> dict[str, str]:
        if self._sandbox_policy.allowed_network_endpoints:
            raise ModelWorkerError("model worker network policy must deny all endpoints")
        environment = self._sandbox_policy.sanitize_environment(inherited)
        environment.update(
            {
                "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "PYTHONHASHSEED": "0",
            }
        )
        return environment

    def _invoke(self, operation: str, payload: dict[str, object]) -> object:
        request = {
            "operation": operation,
            "protocol_version": MODEL_WORKER_PROTOCOL_VERSION,
            "payload": payload,
        }
        environment = self.sanitized_environment(os.environ)
        try:
            result = subprocess.run(
                [self._python_executable, "-B", str(self._script_path)],
                input=json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
                env=environment,
                cwd=self._script_path.parent,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ModelWorkerError("model worker failed to execute") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or "worker exited without error detail"
            raise ModelWorkerError(f"model worker failed explicitly: {detail}")
        if result.stderr.strip():
            raise ModelWorkerError("model worker emitted unexpected stderr")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ModelWorkerError("model worker returned invalid JSON") from error

    @staticmethod
    def _training_rows(samples: tuple[object, ...]) -> list[dict[str, object]]:
        return [
            {
                "sample_id": sample.sample_id,
                "features": sample.feature_wire(),
                "label": float(sample.label),
            }
            for sample in samples
        ]

    def train(
        self, training_spec: TrainingSpecVersion, view: TrainingDatasetView
    ) -> WorkerTrainingCandidate:
        payload = {
            "spec": {
                "alpha": training_spec.alpha,
                "fit_intercept": training_spec.fit_intercept,
                "solver": training_spec.solver,
                "feature_order": list(training_spec.feature_order),
                "seed": training_spec.seed,
            },
            "train_rows": self._training_rows(view.train_samples),
            "validation_rows": self._training_rows(view.validation_samples),
        }
        candidate = WorkerTrainingCandidate.from_wire(
            self._invoke("train_ridge", payload)
        )
        if candidate.runtime != self.runtime:
            raise ModelWorkerError("training runtime drifted after worker admission")
        return candidate

    def predict(
        self,
        training_spec: TrainingSpecVersion,
        artifact: SafeLinearModelArtifact,
        view: PredictionDatasetView,
    ) -> WorkerPredictionCandidate:
        if artifact.feature_order != training_spec.feature_order:
            raise ValueError("safe model Artifact feature order mismatch")
        payload = {
            "feature_order": list(artifact.feature_order),
            "coefficients": list(artifact.coefficients),
            "intercept": artifact.intercept,
            "rows": [
                {
                    "sample_id": sample.sample_id,
                    "features": sample.feature_wire(),
                }
                for sample in view.samples
            ],
        }
        candidate = WorkerPredictionCandidate.from_wire(
            self._invoke("predict_linear", payload)
        )
        if candidate.runtime != self.runtime:
            raise ModelWorkerError("prediction runtime drifted after worker admission")
        return candidate


__all__ = ["ModelWorkerError", "SklearnRidgeSubprocessWorker"]
