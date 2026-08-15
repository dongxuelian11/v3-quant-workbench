CREATE TABLE risk_application_receipt_publication (
  risk_application_receipt_id TEXT PRIMARY KEY
    CHECK(risk_application_receipt_id GLOB 'rar_sha256_*'),
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  artifact_reference_id TEXT NOT NULL UNIQUE
    REFERENCES artifact_reference(artifact_reference_id),
  artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
  byte_size INTEGER NOT NULL CHECK(byte_size>0),
  schema_version TEXT NOT NULL,
  serialization_version TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES project(project_id),
  project_context_revision_id TEXT NOT NULL
    REFERENCES project_context_revision(project_context_revision_id),
  context_identity TEXT NOT NULL CHECK(length(context_identity)=64),
  source_target_weight_vector_id TEXT NOT NULL
    REFERENCES target_weight_vector_publication(target_weight_vector_id),
  source_target_content_sha256 TEXT NOT NULL CHECK(length(source_target_content_sha256)=64),
  risk_policy_set_version_id TEXT NOT NULL
    REFERENCES risk_policy_set_publication(risk_policy_set_version_id),
  risk_policy_set_content_sha256 TEXT NOT NULL CHECK(length(risk_policy_set_content_sha256)=64),
  decision TEXT NOT NULL CHECK(decision IN ('PASS_THROUGH','ADJUSTED')),
  decision_reason TEXT NOT NULL
    CHECK(decision_reason IN ('NO_ADDITIONAL_RISK_TRANSFORM','POLICY_TRANSFORM_APPLIED')),
  ordered_stage_evidence_sha256 TEXT NOT NULL CHECK(length(ordered_stage_evidence_sha256)=64),
  code_version TEXT NOT NULL,
  runtime_profile_id TEXT NOT NULL,
  environment_fingerprint TEXT NOT NULL,
  truth_state TEXT NOT NULL CHECK(truth_state IN ('UNKNOWN','NOT_FORMAL','FORMAL')),
  admission_state TEXT NOT NULL CHECK(admission_state IN ('UNKNOWN','PRE_ALPHA','FORMAL_ADMITTED')),
  published_at TEXT NOT NULL,
  CHECK(risk_application_receipt_id='rar_sha256_' || content_sha256),
  CHECK(artifact_id='art_sha256_' || artifact_sha256)
);

CREATE TABLE risk_adjusted_weight_vector_publication (
  risk_adjusted_weight_vector_id TEXT PRIMARY KEY
    CHECK(risk_adjusted_weight_vector_id GLOB 'rawv_sha256_*'),
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  artifact_reference_id TEXT NOT NULL UNIQUE
    REFERENCES artifact_reference(artifact_reference_id),
  artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
  byte_size INTEGER NOT NULL CHECK(byte_size>0),
  schema_version TEXT NOT NULL,
  serialization_version TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES project(project_id),
  project_context_revision_id TEXT NOT NULL
    REFERENCES project_context_revision(project_context_revision_id),
  context_identity TEXT NOT NULL CHECK(length(context_identity)=64),
  source_target_weight_vector_id TEXT NOT NULL
    REFERENCES target_weight_vector_publication(target_weight_vector_id),
  source_target_content_sha256 TEXT NOT NULL CHECK(length(source_target_content_sha256)=64),
  risk_application_receipt_id TEXT NOT NULL
    REFERENCES risk_application_receipt_publication(risk_application_receipt_id),
  risk_application_content_sha256 TEXT NOT NULL CHECK(length(risk_application_content_sha256)=64),
  code_version TEXT NOT NULL,
  runtime_profile_id TEXT NOT NULL,
  environment_fingerprint TEXT NOT NULL,
  truth_state TEXT NOT NULL CHECK(truth_state IN ('UNKNOWN','NOT_FORMAL','FORMAL')),
  admission_state TEXT NOT NULL CHECK(admission_state IN ('UNKNOWN','PRE_ALPHA','FORMAL_ADMITTED')),
  published_at TEXT NOT NULL,
  CHECK(risk_adjusted_weight_vector_id='rawv_sha256_' || content_sha256),
  CHECK(artifact_id='art_sha256_' || artifact_sha256)
);

CREATE INDEX idx_risk_application_receipt_context
  ON risk_application_receipt_publication(
    project_id,project_context_revision_id,context_identity
  );
CREATE INDEX idx_risk_adjusted_vector_context
  ON risk_adjusted_weight_vector_publication(
    project_id,project_context_revision_id,context_identity
  );

CREATE TRIGGER trg_risk_application_receipt_artifact_i
BEFORE INSERT ON risk_application_receipt_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact
  WHERE artifact_id=NEW.artifact_id
    AND sha256=NEW.artifact_sha256
    AND byte_size=NEW.byte_size
    AND media_type='application/json'
    AND semantic_role='RISK_APPLICATION_RECEIPT'
    AND state='PUBLISHED'
)
BEGIN
  SELECT RAISE(ABORT,'RiskApplicationReceipt requires exact PUBLISHED Artifact bytes');
END;

CREATE TRIGGER trg_risk_application_receipt_reference_i
BEFORE INSERT ON risk_application_receipt_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact_reference
  WHERE artifact_reference_id=NEW.artifact_reference_id
    AND owner_type='RiskApplicationReceipt'
    AND owner_id=NEW.risk_application_receipt_id
    AND role='RISK_APPLICATION_RECEIPT'
    AND artifact_id=NEW.artifact_id
    AND state='ACTIVE'
)
BEGIN
  SELECT RAISE(ABORT,'RiskApplicationReceipt requires its exact active Artifact reference');
END;

CREATE TRIGGER trg_risk_adjusted_vector_artifact_i
BEFORE INSERT ON risk_adjusted_weight_vector_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact
  WHERE artifact_id=NEW.artifact_id
    AND sha256=NEW.artifact_sha256
    AND byte_size=NEW.byte_size
    AND media_type='application/json'
    AND semantic_role='RISK_ADJUSTED_WEIGHT_VECTOR'
    AND state='PUBLISHED'
)
BEGIN
  SELECT RAISE(ABORT,'RiskAdjustedWeightVector requires exact PUBLISHED Artifact bytes');
END;

CREATE TRIGGER trg_risk_adjusted_vector_reference_i
BEFORE INSERT ON risk_adjusted_weight_vector_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact_reference
  WHERE artifact_reference_id=NEW.artifact_reference_id
    AND owner_type='RiskAdjustedWeightVector'
    AND owner_id=NEW.risk_adjusted_weight_vector_id
    AND role='RISK_ADJUSTED_WEIGHT_VECTOR'
    AND artifact_id=NEW.artifact_id
    AND state='ACTIVE'
)
BEGIN
  SELECT RAISE(ABORT,'RiskAdjustedWeightVector requires its exact active Artifact reference');
END;

CREATE TRIGGER trg_risk_application_upstream_owners_i
BEFORE INSERT ON risk_application_receipt_publication
WHEN NOT EXISTS (
  SELECT 1
  FROM target_weight_vector_publication AS target
  JOIN risk_policy_set_publication AS policy
    ON policy.project_id=target.project_id
   AND policy.project_context_revision_id=target.project_context_revision_id
   AND policy.context_identity=target.context_identity
  WHERE target.target_weight_vector_id=NEW.source_target_weight_vector_id
    AND target.content_sha256=NEW.source_target_content_sha256
    AND policy.risk_policy_set_version_id=NEW.risk_policy_set_version_id
    AND policy.content_sha256=NEW.risk_policy_set_content_sha256
    AND policy.risk_model_requirement='NOT_REQUIRED'
    AND target.project_id=NEW.project_id
    AND target.project_context_revision_id=NEW.project_context_revision_id
    AND target.context_identity=NEW.context_identity
)
BEGIN
  SELECT RAISE(ABORT,'RiskApplicationReceipt upstream owner/hash/project/context mismatch');
END;

CREATE TRIGGER trg_risk_adjusted_lineage_i
BEFORE INSERT ON risk_adjusted_weight_vector_publication
WHEN NOT EXISTS (
  SELECT 1
  FROM risk_application_receipt_publication AS receipt
  JOIN target_weight_vector_publication AS target
    ON target.target_weight_vector_id=receipt.source_target_weight_vector_id
  WHERE receipt.risk_application_receipt_id=NEW.risk_application_receipt_id
    AND receipt.content_sha256=NEW.risk_application_content_sha256
    AND receipt.source_target_weight_vector_id=NEW.source_target_weight_vector_id
    AND receipt.source_target_content_sha256=NEW.source_target_content_sha256
    AND receipt.project_id=NEW.project_id
    AND receipt.project_context_revision_id=NEW.project_context_revision_id
    AND receipt.context_identity=NEW.context_identity
    AND target.project_id=NEW.project_id
    AND target.project_context_revision_id=NEW.project_context_revision_id
    AND target.context_identity=NEW.context_identity
)
BEGIN
  SELECT RAISE(ABORT,'RiskAdjustedWeightVector lineage mismatch');
END;

CREATE TRIGGER trg_risk_application_receipt_append_only_u
BEFORE UPDATE ON risk_application_receipt_publication
BEGIN
  SELECT RAISE(ABORT,'risk_application_receipt_publication is append-only');
END;

CREATE TRIGGER trg_risk_application_receipt_append_only_d
BEFORE DELETE ON risk_application_receipt_publication
BEGIN
  SELECT RAISE(ABORT,'risk_application_receipt_publication is append-only');
END;

CREATE TRIGGER trg_risk_adjusted_vector_append_only_u
BEFORE UPDATE ON risk_adjusted_weight_vector_publication
BEGIN
  SELECT RAISE(ABORT,'risk_adjusted_weight_vector_publication is append-only');
END;

CREATE TRIGGER trg_risk_adjusted_vector_append_only_d
BEFORE DELETE ON risk_adjusted_weight_vector_publication
BEGIN
  SELECT RAISE(ABORT,'risk_adjusted_weight_vector_publication is append-only');
END;
