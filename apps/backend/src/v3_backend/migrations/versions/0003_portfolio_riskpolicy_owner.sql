CREATE TABLE target_weight_vector_publication (
  target_weight_vector_id TEXT PRIMARY KEY
    CHECK(target_weight_vector_id GLOB 'twv_sha256_*'),
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  project_context_revision_id TEXT NOT NULL
    REFERENCES project_context_revision(project_context_revision_id),
  context_identity TEXT NOT NULL CHECK(length(context_identity)=64),
  portfolio_intent_id TEXT NOT NULL CHECK(portfolio_intent_id GLOB 'pint_sha256_*'),
  portfolio_intent_content_sha256 TEXT NOT NULL CHECK(length(portfolio_intent_content_sha256)=64),
  portfolio_intent_provenance_sha256 TEXT NOT NULL CHECK(length(portfolio_intent_provenance_sha256)=64),
  source_reference_sha256 TEXT NOT NULL CHECK(length(source_reference_sha256)=64),
  source_owner_receipt_resolution TEXT NOT NULL
    CHECK(source_owner_receipt_resolution='UNRESOLVED_CALLER_ASSERTED'),
  construction_spec_id TEXT NOT NULL,
  construction_spec_content_sha256 TEXT NOT NULL CHECK(length(construction_spec_content_sha256)=64),
  universe_version_id TEXT NOT NULL,
  membership_artifact_id TEXT NOT NULL,
  membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  artifact_reference_id TEXT NOT NULL UNIQUE
    REFERENCES artifact_reference(artifact_reference_id),
  artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
  byte_size INTEGER NOT NULL CHECK(byte_size>0),
  schema_version TEXT NOT NULL,
  serialization_version TEXT NOT NULL,
  canonical_truth_state TEXT NOT NULL
    CHECK(canonical_truth_state IN ('UNKNOWN','NOT_FORMAL','FORMAL')),
  canonical_admission_state TEXT NOT NULL
    CHECK(canonical_admission_state IN ('UNKNOWN','PRE_ALPHA','FORMAL_ADMITTED')),
  created_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  CHECK(target_weight_vector_id='twv_sha256_' || content_sha256),
  CHECK(artifact_id='art_sha256_' || artifact_sha256),
  CHECK(canonical_admission_state<>'PRE_ALPHA' OR canonical_truth_state IN ('NOT_FORMAL','FORMAL'))
);

CREATE TABLE risk_policy_set_publication (
  risk_policy_set_version_id TEXT PRIMARY KEY
    CHECK(risk_policy_set_version_id GLOB 'rpsv_sha256_*'),
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  project_context_revision_id TEXT NOT NULL
    REFERENCES project_context_revision(project_context_revision_id),
  context_identity TEXT NOT NULL CHECK(length(context_identity)=64),
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  artifact_reference_id TEXT NOT NULL UNIQUE
    REFERENCES artifact_reference(artifact_reference_id),
  artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
  byte_size INTEGER NOT NULL CHECK(byte_size>0),
  schema_version TEXT NOT NULL,
  serialization_version TEXT NOT NULL,
  authoring_service_version TEXT NOT NULL,
  code_version TEXT NOT NULL,
  runtime_profile_id TEXT NOT NULL,
  environment_fingerprint TEXT NOT NULL,
  backend TEXT NOT NULL,
  risk_model_requirement TEXT NOT NULL CHECK(risk_model_requirement='NOT_REQUIRED'),
  canonical_truth_state TEXT NOT NULL
    CHECK(canonical_truth_state IN ('UNKNOWN','NOT_FORMAL','FORMAL')),
  canonical_admission_state TEXT NOT NULL
    CHECK(canonical_admission_state IN ('UNKNOWN','PRE_ALPHA','FORMAL_ADMITTED')),
  created_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  CHECK(risk_policy_set_version_id='rpsv_sha256_' || content_sha256),
  CHECK(artifact_id='art_sha256_' || artifact_sha256),
  CHECK(canonical_admission_state<>'PRE_ALPHA' OR canonical_truth_state IN ('NOT_FORMAL','FORMAL'))
);

CREATE INDEX idx_target_weight_owner_context
  ON target_weight_vector_publication(project_id,project_context_revision_id,context_identity);
CREATE INDEX idx_risk_policy_owner_context
  ON risk_policy_set_publication(project_id,project_context_revision_id,context_identity);

CREATE TRIGGER trg_target_weight_owner_project_context_i
BEFORE INSERT ON target_weight_vector_publication
WHEN NOT EXISTS (
  SELECT 1
  FROM project AS project
  JOIN project_context_revision AS revision
    ON revision.project_id=project.project_id
  WHERE project.project_id=NEW.project_id
    AND project.state='ACTIVE'
    AND revision.project_context_revision_id=NEW.project_context_revision_id
)
BEGIN
  SELECT RAISE(ABORT,'TargetWeight owner requires an exact active Project/ProjectContext');
END;

CREATE TRIGGER trg_risk_policy_owner_project_context_i
BEFORE INSERT ON risk_policy_set_publication
WHEN NOT EXISTS (
  SELECT 1
  FROM project AS project
  JOIN project_context_revision AS revision
    ON revision.project_id=project.project_id
  WHERE project.project_id=NEW.project_id
    AND project.state='ACTIVE'
    AND revision.project_context_revision_id=NEW.project_context_revision_id
)
BEGIN
  SELECT RAISE(ABORT,'RiskPolicy owner requires an exact active Project/ProjectContext');
END;

CREATE TRIGGER trg_target_weight_owner_artifact_i
BEFORE INSERT ON target_weight_vector_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact
  WHERE artifact_id=NEW.artifact_id
    AND sha256=NEW.artifact_sha256
    AND byte_size=NEW.byte_size
    AND media_type='application/json'
    AND semantic_role='TARGET_WEIGHT_VECTOR'
    AND state='PUBLISHED'
)
BEGIN
  SELECT RAISE(ABORT,'TargetWeight owner requires exact PUBLISHED Artifact bytes');
END;

CREATE TRIGGER trg_risk_policy_owner_artifact_i
BEFORE INSERT ON risk_policy_set_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact
  WHERE artifact_id=NEW.artifact_id
    AND sha256=NEW.artifact_sha256
    AND byte_size=NEW.byte_size
    AND media_type='application/json'
    AND semantic_role='RISK_POLICY_SET'
    AND state='PUBLISHED'
)
BEGIN
  SELECT RAISE(ABORT,'RiskPolicy owner requires exact PUBLISHED Artifact bytes');
END;

CREATE TRIGGER trg_target_weight_owner_reference_i
BEFORE INSERT ON target_weight_vector_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact_reference
  WHERE artifact_reference_id=NEW.artifact_reference_id
    AND owner_type='TargetWeightVector'
    AND owner_id=NEW.target_weight_vector_id
    AND role='TARGET_WEIGHT_VECTOR'
    AND artifact_id=NEW.artifact_id
    AND state='ACTIVE'
)
BEGIN
  SELECT RAISE(ABORT,'TargetWeight owner requires its exact active Artifact reference');
END;

CREATE TRIGGER trg_risk_policy_owner_reference_i
BEFORE INSERT ON risk_policy_set_publication
WHEN NOT EXISTS (
  SELECT 1 FROM artifact_reference
  WHERE artifact_reference_id=NEW.artifact_reference_id
    AND owner_type='RiskPolicySetVersion'
    AND owner_id=NEW.risk_policy_set_version_id
    AND role='RISK_POLICY_SET'
    AND artifact_id=NEW.artifact_id
    AND state='ACTIVE'
)
BEGIN
  SELECT RAISE(ABORT,'RiskPolicy owner requires its exact active Artifact reference');
END;

CREATE TRIGGER trg_target_weight_owner_append_only_u
BEFORE UPDATE ON target_weight_vector_publication
BEGIN
  SELECT RAISE(ABORT,'target_weight_vector_publication is append-only');
END;

CREATE TRIGGER trg_target_weight_owner_append_only_d
BEFORE DELETE ON target_weight_vector_publication
BEGIN
  SELECT RAISE(ABORT,'target_weight_vector_publication is append-only');
END;

CREATE TRIGGER trg_risk_policy_owner_append_only_u
BEFORE UPDATE ON risk_policy_set_publication
BEGIN
  SELECT RAISE(ABORT,'risk_policy_set_publication is append-only');
END;

CREATE TRIGGER trg_risk_policy_owner_append_only_d
BEFORE DELETE ON risk_policy_set_publication
BEGIN
  SELECT RAISE(ABORT,'risk_policy_set_publication is append-only');
END;
