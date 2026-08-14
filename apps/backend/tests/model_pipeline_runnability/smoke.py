"""Repo-native bounded Model pipeline smoke using actual A1/P1 bytes and worker."""

from __future__ import annotations

import json

from apps.backend.tests.model_pipeline_runnability.helpers import (
    build_model_pipeline_development_fixture,
)
from apps.backend.tests.model_pipeline_runnability.test_model_pipeline import request
from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.model_workers import SklearnRidgeSubprocessWorker
from v3_backend.domain.models import (
    ModelPipelineStatus,
    SAFE_LINEAR_MODEL_MEDIA_TYPE,
    SafeLinearModelArtifact,
)


def main() -> int:
    fixture = build_model_pipeline_development_fixture(SklearnRidgeSubprocessWorker())
    try:
        result = fixture.service.run(request(fixture.dataset.dataset_version_id))
        if result.status is not ModelPipelineStatus.SUCCESS:
            print(json.dumps(result.to_wire(), ensure_ascii=False, sort_keys=True))
            return 1
        reopened = FileSystemArtifactStore(fixture.store.root)
        safe_model = SafeLinearModelArtifact.from_bytes(
            SAFE_LINEAR_MODEL_MEDIA_TYPE,
            reopened.read_bytes(result.model_artifact_id),
        )
        prediction = json.loads(reopened.read_bytes(result.prediction_artifact_id))
        if (
            safe_model.artifact_id != result.model_artifact_id
            or prediction.get("prediction_artifact_id") != result.prediction_id
        ):
            raise RuntimeError("restart/reopen artifact verification failed")
        print(json.dumps(result.to_wire(), ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        fixture.close()


if __name__ == "__main__":
    raise SystemExit(main())
