"""Bounded local A1/P1 fixture for the Model pipeline smoke and tests."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from apps.backend.tests.systemic_a1_payload_closure.test_sqlite_canonical_owner_label_persistence import (
    ContextRepository,
    SQLiteCanonicalOwnerClosureTests,
    SpecRepository,
)
from v3_backend.adapters.model_pipeline_artifacts import FileSystemModelPipelineArtifactPublisher
from v3_backend.adapters.systemic_a1_payload import A1CanonicalPayloadBindingResolver
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.datasets import (
    FormalDatasetBuildRequest,
    SplitSpec,
)
from v3_backend.domain.factors import FormalFactorEvaluationRequest
from v3_backend.domain.models import (
    CanonicalDatasetModelPipelineService,
    ModelPipelineDependencies,
)
from v3_backend.domain.payload_authority import CanonicalPayloadResolver


@dataclass(slots=True)
class ModelPipelineDevelopmentFixture:
    case: SQLiteCanonicalOwnerClosureTests
    connection: object
    unit_of_work: object
    owner: object
    dataset: object
    split_spec: SplitSpec
    service: CanonicalDatasetModelPipelineService

    @property
    def store(self):
        return self.case.store

    def close(self) -> None:
        self.unit_of_work.rollback()
        self.connection.close()
        self.case.tearDown()


class ExtendedObservationA1Fixture(SQLiteCanonicalOwnerClosureTests):
    def _publish_store(self, payload, *, schema, semantic_role="FACTOR_INPUT"):
        if isinstance(payload, dict) and "observation_ids" in payload and "fields" in payload:
            payload = copy.deepcopy(payload)
            payload["observation_ids"] = ["s0", "s1", "s2", "s3", "s4", "s5"]
            payload["fields"][0]["shape"] = [2, 6]
            payload["fields"][0]["values"] = [
                "10", "11", "12", "13", "14", "15",
                "20", "21", "22", "23", "24", "25",
            ]
        return super()._publish_store(payload, schema=schema, semantic_role=semantic_role)


def build_model_pipeline_development_fixture(worker) -> ModelPipelineDevelopmentFixture:
    case = ExtendedObservationA1Fixture(
        "test_a1_p01_p10_reopen_persistence_and_neg_c"
    )
    case.setUp()
    case.split = SplitSpec.create(
        train_start=0,
        train_end=0,
        validation_start=2,
        validation_end=2,
        test_start=4,
        test_end=4,
        purge_observations=0,
        embargo_observations=0,
    )
    connection, unit_of_work, owner, resolver = case._runtime()
    try:
        materialization = case._factor_service(owner, resolver).evaluate(
            FormalFactorEvaluationRequest(
                case.definition.factor_definition_version_id,
                "snp_a1",
                "unv_a1",
                100_000,
                PRE_ALPHA_CEILING,
            )
        )
        case._label_service(owner, resolver).materialize(
            label_spec_id=case.label.label_spec_id,
            snapshot_id="snp_a1",
            universe_version_id="unv_a1",
            max_payload_bytes=100_000,
        )
        dataset = case._dataset_service(owner, resolver).build(
            FormalDatasetBuildRequest(
                (materialization.feature_materialization_id,),
                case.label.label_spec_id,
                case.split.split_spec_id,
                "snp_a1",
                "unv_a1",
                100_000,
                PRE_ALPHA_CEILING,
            )
        )
        unit_of_work.commit()
    finally:
        connection.close()

    connection, unit_of_work, owner, _ = case._runtime(read_only=True)
    contexts = ContextRepository(owner, case.definitions, case.label_specs)
    binding = A1CanonicalPayloadBindingResolver(
        snapshots=owner,
        factor_contexts=contexts,
        materializations=owner,
        label_payloads=owner,
        label_contexts=contexts,
        datasets=owner,
    )
    payload_resolver = CanonicalPayloadResolver(
        binding_resolver=binding,
        byte_reader=case.store,
    )
    service = CanonicalDatasetModelPipelineService(
        ModelPipelineDependencies(
            datasets=owner,
            split_specs=SpecRepository(case.split),
            payload_resolver=payload_resolver,
            worker=worker,
            artifact_publisher=FileSystemModelPipelineArtifactPublisher(case.store),
        )
    )
    return ModelPipelineDevelopmentFixture(
        case=case,
        connection=connection,
        unit_of_work=unit_of_work,
        owner=owner,
        dataset=dataset,
        split_spec=case.split,
        service=service,
    )


__all__ = [
    "ModelPipelineDevelopmentFixture",
    "build_model_pipeline_development_fixture",
]
