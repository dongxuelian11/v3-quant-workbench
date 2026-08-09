-- V3 Canonical Backend Control Catalog schema specification v1.0.0
-- SPECIFICATION ONLY. DO NOT APPLY AS PART OF BR-0.
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migration (
  migration_id TEXT PRIMARY KEY,
  checksum_sha256 TEXT NOT NULL CHECK(length(checksum_sha256)=64),
  applied_at TEXT NOT NULL,
  application_version TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('APPLYING','APPLIED','ROLLED_BACK')),
  backup_artifact_id TEXT
);

CREATE TABLE project (
  project_id TEXT PRIMARY KEY CHECK(project_id GLOB 'prj_*'),
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  archived_at TEXT,
  state TEXT NOT NULL CHECK(state IN ('ACTIVE','ARCHIVED')),
  row_version INTEGER NOT NULL DEFAULT 0 CHECK(row_version>=0)
);

CREATE TABLE connector (
  connector_id TEXT PRIMARY KEY CHECK(connector_id GLOB 'con_*'),
  stable_name TEXT NOT NULL UNIQUE,
  publisher TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('REGISTERED','DISABLED')),
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE connector_version (
  connector_version_id TEXT PRIMARY KEY CHECK(connector_version_id GLOB 'cov_*'),
  connector_id TEXT NOT NULL REFERENCES connector(connector_id),
  semantic_version TEXT NOT NULL,
  bundle_artifact_id TEXT NOT NULL,
  bundle_sha256 TEXT NOT NULL CHECK(length(bundle_sha256)=64),
  entrypoint TEXT NOT NULL,
  declared_manifest_json TEXT NOT NULL CHECK(length(declared_manifest_json)<=65536),
  network_policy TEXT NOT NULL CHECK(network_policy IN ('DENY','DECLARED_ALLOWLIST')),
  state TEXT NOT NULL CHECK(state IN ('QUARANTINED','ADMITTED','REJECTED','RETIRED')),
  created_at TEXT NOT NULL,
  retired_at TEXT,
  UNIQUE(connector_id,semantic_version,bundle_sha256)
);

CREATE TABLE connector_capability (
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  capability_code TEXT NOT NULL,
  declared_state TEXT NOT NULL CHECK(declared_state IN ('DECLARED','NOT_DECLARED')),
  admitted_truth_state TEXT NOT NULL CHECK(admitted_truth_state IN ('FORMAL','DEMO','UNAVAILABLE')),
  limitation_json TEXT CHECK(limitation_json IS NULL OR length(limitation_json)<=32768),
  evidence_artifact_id TEXT,
  PRIMARY KEY(connector_version_id,capability_code)
);

CREATE TABLE connector_admission (
  connector_admission_id TEXT PRIMARY KEY CHECK(connector_admission_id GLOB 'cad_*'),
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  admission_profile_id TEXT NOT NULL,
  environment_profile_id TEXT NOT NULL,
  task_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('PENDING','RUNNING','PASSED','FAILED')),
  report_artifact_id TEXT,
  started_at TEXT,
  finished_at TEXT,
  UNIQUE(connector_version_id,admission_profile_id,environment_profile_id)
);

CREATE TABLE credential_reference (
  credential_reference_id TEXT PRIMARY KEY CHECK(credential_reference_id GLOB 'crf_*'),
  connector_id TEXT NOT NULL REFERENCES connector(connector_id),
  windows_credential_target TEXT NOT NULL UNIQUE,
  principal_hint TEXT,
  state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')),
  created_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE data_snapshot (
  snapshot_id TEXT PRIMARY KEY CHECK(snapshot_id GLOB 'snp_*'),
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  parent_snapshot_id TEXT REFERENCES data_snapshot(snapshot_id),
  manifest_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  normalization_spec_version TEXT NOT NULL,
  truth_profile_id TEXT NOT NULL,
  min_effective_time TEXT,
  max_effective_time TEXT,
  max_available_time TEXT,
  state TEXT NOT NULL CHECK(state IN ('CANDIDATE','VALIDATED','PUBLISHED','REJECTED')),
  created_at TEXT NOT NULL,
  validated_at TEXT,
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (manifest_artifact_id IS NOT NULL AND content_hash IS NOT NULL AND published_at IS NOT NULL))
);

CREATE TABLE project_context_revision (
  project_context_revision_id TEXT PRIMARY KEY CHECK(project_context_revision_id GLOB 'pcr_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  revision_no INTEGER NOT NULL CHECK(revision_no>=1),
  parent_revision_id TEXT REFERENCES project_context_revision(project_context_revision_id),
  connector_version_id TEXT REFERENCES connector_version(connector_version_id),
  snapshot_id TEXT REFERENCES data_snapshot(snapshot_id),
  universe_version_id TEXT,
  environment_profile_id TEXT,
  context_json TEXT NOT NULL CHECK(length(context_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(project_id,revision_no),
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE desktop_session (
  session_id TEXT PRIMARY KEY CHECK(session_id GLOB 'ses_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  project_context_revision_id TEXT NOT NULL REFERENCES project_context_revision(project_context_revision_id),
  layout_artifact_id TEXT,
  active_lab TEXT CHECK(active_lab IN ('RESEARCH','STRATEGY','MODEL','BACKTEST','RESULT')),
  state TEXT NOT NULL CHECK(state IN ('OPEN','CLOSED')),
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  row_version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE instrument (
  instrument_id TEXT PRIMARY KEY CHECK(instrument_id GLOB 'ins_*'),
  asset_class TEXT NOT NULL CHECK(asset_class='CN_A_SHARE'),
  exchange TEXT NOT NULL CHECK(exchange IN ('SSE','SZSE','BSE')),
  listing_date TEXT NOT NULL,
  delisting_date TEXT,
  state TEXT NOT NULL CHECK(state IN ('ACTIVE','DELISTED','MERGED')),
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL DEFAULT 0,
  CHECK(delisting_date IS NULL OR delisting_date>=listing_date)
);

CREATE TABLE instrument_revision (
  instrument_revision_id TEXT PRIMARY KEY CHECK(instrument_revision_id GLOB 'inr_*'),
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  revision_no INTEGER NOT NULL CHECK(revision_no>=1),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  available_time TEXT NOT NULL,
  revision_id TEXT NOT NULL,
  name TEXT NOT NULL,
  lifecycle_json TEXT NOT NULL CHECK(length(lifecycle_json)<=32768),
  provider TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  evidence_artifact_id TEXT NOT NULL,
  UNIQUE(instrument_id,revision_no),
  CHECK(effective_to IS NULL OR effective_to>effective_from)
);

CREATE TABLE instrument_alias (
  instrument_alias_id TEXT PRIMARY KEY CHECK(instrument_alias_id GLOB 'ial_*'),
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  provider_code TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  available_time TEXT NOT NULL,
  evidence_artifact_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(connector_version_id,provider_code,effective_from),
  CHECK(effective_to IS NULL OR effective_to>effective_from)
);

CREATE TABLE raw_capture (
  raw_capture_id TEXT PRIMARY KEY CHECK(raw_capture_id GLOB 'raw_*'),
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  provider_dataset TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
  effective_range_start TEXT,
  effective_range_end TEXT,
  available_time TEXT NOT NULL,
  provider_revision_id TEXT,
  captured_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('CAPTURED','QUARANTINED','ACCEPTED')),
  UNIQUE(connector_version_id,request_fingerprint,content_hash)
);

CREATE TABLE snapshot_partition (
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  logical_dataset TEXT NOT NULL,
  partition_key TEXT NOT NULL,
  parquet_artifact_id TEXT NOT NULL,
  row_count INTEGER NOT NULL CHECK(row_count>=0),
  schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64),
  min_effective_time TEXT,
  max_effective_time TEXT,
  max_available_time TEXT,
  PRIMARY KEY(snapshot_id,logical_dataset,partition_key)
);

CREATE TABLE snapshot_validation (
  snapshot_validation_id TEXT PRIMARY KEY CHECK(snapshot_validation_id GLOB 'snv_*'),
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  validation_profile_id TEXT NOT NULL,
  check_code TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('PASS','FAIL','NOT_APPLICABLE')),
  severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','BLOCKING')),
  report_artifact_id TEXT NOT NULL,
  validated_at TEXT NOT NULL,
  UNIQUE(snapshot_id,validation_profile_id,check_code)
);

CREATE TABLE industry_taxonomy_version (
  industry_taxonomy_version_id TEXT PRIMARY KEY CHECK(industry_taxonomy_version_id GLOB 'itx_*'),
  taxonomy_name TEXT NOT NULL,
  taxonomy_revision TEXT NOT NULL,
  manifest_artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  published_at TEXT NOT NULL,
  UNIQUE(taxonomy_name,taxonomy_revision,content_hash)
);

CREATE TABLE industry_membership (
  industry_taxonomy_version_id TEXT NOT NULL REFERENCES industry_taxonomy_version(industry_taxonomy_version_id),
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  industry_code TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  available_time TEXT NOT NULL,
  revision_id TEXT NOT NULL,
  evidence_artifact_id TEXT NOT NULL,
  PRIMARY KEY(industry_taxonomy_version_id,instrument_id,industry_code,effective_from),
  CHECK(effective_to IS NULL OR effective_to>effective_from)
);

CREATE TABLE universe_definition (
  universe_definition_id TEXT PRIMARY KEY CHECK(universe_definition_id GLOB 'und_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  constructor_kind TEXT NOT NULL CHECK(constructor_kind IN ('ALL_A','INDEX','INDUSTRY','WATCHLIST','CSV_TSV','QUERY','INTERSECTION','UNION','DIFFERENCE')),
  definition_json TEXT NOT NULL CHECK(length(definition_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','PUBLISHED')),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE universe_version (
  universe_version_id TEXT PRIMARY KEY CHECK(universe_version_id GLOB 'unv_*'),
  universe_definition_id TEXT NOT NULL REFERENCES universe_definition(universe_definition_id),
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  industry_taxonomy_version_id TEXT REFERENCES industry_taxonomy_version(industry_taxonomy_version_id),
  knowledge_cutoff TEXT NOT NULL,
  membership_artifact_id TEXT,
  audit_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('BUILDING','PUBLISHED','REJECTED')),
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (membership_artifact_id IS NOT NULL AND audit_artifact_id IS NOT NULL AND content_hash IS NOT NULL))
);

CREATE TABLE factor_definition (
  factor_definition_id TEXT PRIMARY KEY CHECK(factor_definition_id GLOB 'fad_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  stable_name TEXT NOT NULL,
  definition_json TEXT NOT NULL CHECK(length(definition_json)<=65536),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,stable_name)
);

CREATE TABLE factor_version (
  factor_version_id TEXT PRIMARY KEY CHECK(factor_version_id GLOB 'fav_*'),
  factor_definition_id TEXT NOT NULL REFERENCES factor_definition(factor_definition_id),
  semantic_version TEXT NOT NULL,
  code_artifact_id TEXT NOT NULL,
  code_hash TEXT NOT NULL CHECK(length(code_hash)=64),
  availability_policy_json TEXT NOT NULL CHECK(length(availability_policy_json)<=32768),
  state TEXT NOT NULL CHECK(state IN ('PUBLISHED','RETIRED')),
  published_at TEXT NOT NULL,
  UNIQUE(factor_definition_id,semantic_version,code_hash)
);

CREATE TABLE dataset_spec (
  dataset_spec_id TEXT PRIMARY KEY CHECK(dataset_spec_id GLOB 'dss_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  spec_json TEXT NOT NULL CHECK(length(spec_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  split_kind TEXT NOT NULL CHECK(split_kind IN ('CHRONOLOGICAL','ROLLING','EXPANDING')),
  purge_duration TEXT,
  embargo_duration TEXT,
  preprocessing_fit_scope TEXT NOT NULL CHECK(preprocessing_fit_scope='TRAIN_ONLY'),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','VALIDATED','REJECTED')),
  validation_artifact_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE dataset_version (
  dataset_version_id TEXT PRIMARY KEY CHECK(dataset_version_id GLOB 'dsv_*'),
  dataset_spec_id TEXT NOT NULL REFERENCES dataset_spec(dataset_spec_id),
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  universe_version_id TEXT NOT NULL REFERENCES universe_version(universe_version_id),
  manifest_artifact_id TEXT,
  leakage_audit_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('MATERIALIZING','PUBLISHED','REJECTED')),
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (manifest_artifact_id IS NOT NULL AND leakage_audit_artifact_id IS NOT NULL AND content_hash IS NOT NULL))
);

CREATE TABLE strategy_draft (
  strategy_draft_id TEXT PRIMARY KEY CHECK(strategy_draft_id GLOB 'std_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  revision_no INTEGER NOT NULL CHECK(revision_no>=1),
  draft_artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  mode TEXT NOT NULL CHECK(mode IN ('VISUAL','CODE','SPLIT')),
  state TEXT NOT NULL CHECK(state IN ('EDITABLE','SUPERSEDED')),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,strategy_draft_id,revision_no)
);

CREATE TABLE strategy_version (
  strategy_version_id TEXT PRIMARY KEY CHECK(strategy_version_id GLOB 'stv_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  strategy_ir_artifact_id TEXT NOT NULL,
  validation_artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  compiler_profile_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('PUBLISHED','RETIRED')),
  published_at TEXT NOT NULL,
  UNIQUE(project_id,content_hash,compiler_profile_id)
);

CREATE TABLE model_spec (
  model_spec_id TEXT PRIMARY KEY CHECK(model_spec_id GLOB 'mds_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  model_family TEXT NOT NULL CHECK(model_family IN ('LINEAR','TREE_ENSEMBLE','BOOSTING','SVM','NEURAL_NETWORK','SEQUENCE','ENSEMBLE')),
  spec_json TEXT NOT NULL CHECK(length(spec_json)<=65536),
  environment_profile_id TEXT NOT NULL,
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','VALIDATED')),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE model_version (
  model_version_id TEXT PRIMARY KEY CHECK(model_version_id GLOB 'mdv_*'),
  model_spec_id TEXT NOT NULL REFERENCES model_spec(model_spec_id),
  dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
  run_id TEXT NOT NULL,
  model_artifact_id TEXT,
  metrics_artifact_id TEXT,
  model_card_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  safe_format_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('TRAINING','PUBLISHED','REJECTED')),
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (model_artifact_id IS NOT NULL AND metrics_artifact_id IS NOT NULL AND content_hash IS NOT NULL))
);

CREATE TABLE prediction_signal_version (
  prediction_signal_version_id TEXT PRIMARY KEY CHECK(prediction_signal_version_id GLOB 'sgv_*'),
  model_version_id TEXT NOT NULL REFERENCES model_version(model_version_id),
  dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
  signal_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('GENERATING','PUBLISHED','REJECTED')),
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (signal_artifact_id IS NOT NULL AND content_hash IS NOT NULL))
);

CREATE TABLE study (
  study_id TEXT PRIMARY KEY CHECK(study_id GLOB 'stu_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
  study_spec_json TEXT NOT NULL CHECK(length(study_spec_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('CREATED','RUNNING','PAUSING','PAUSED','COMPLETED','PARTIAL','CANCELLED','FAILED')),
  state_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE trial (
  trial_id TEXT PRIMARY KEY CHECK(trial_id GLOB 'trl_*'),
  study_id TEXT NOT NULL REFERENCES study(study_id),
  trial_no INTEGER NOT NULL CHECK(trial_no>=0),
  parameter_json TEXT NOT NULL CHECK(length(parameter_json)<=32768),
  parameter_hash TEXT NOT NULL CHECK(length(parameter_hash)=64),
  task_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','PRUNED','COMPLETED','FAILED','CANCELLED')),
  objective_summary_json TEXT CHECK(objective_summary_json IS NULL OR length(objective_summary_json)<=32768),
  metrics_artifact_id TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  UNIQUE(study_id,trial_no),
  UNIQUE(study_id,parameter_hash)
);

CREATE TABLE portfolio_construction_spec (
  portfolio_spec_id TEXT PRIMARY KEY CHECK(portfolio_spec_id GLOB 'pcs_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  spec_json TEXT NOT NULL CHECK(length(spec_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','PUBLISHED')),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE portfolio_version (
  portfolio_version_id TEXT PRIMARY KEY CHECK(portfolio_version_id GLOB 'pfv_*'),
  portfolio_spec_id TEXT NOT NULL REFERENCES portfolio_construction_spec(portfolio_spec_id),
  prediction_signal_version_id TEXT REFERENCES prediction_signal_version(prediction_signal_version_id),
  universe_version_id TEXT NOT NULL REFERENCES universe_version(universe_version_id),
  targets_artifact_id TEXT,
  diagnostics_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('BUILDING','PUBLISHED','REJECTED')),
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (targets_artifact_id IS NOT NULL AND content_hash IS NOT NULL))
);

CREATE TABLE risk_model_spec (
  risk_model_spec_id TEXT PRIMARY KEY CHECK(risk_model_spec_id GLOB 'rms_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  spec_json TEXT NOT NULL CHECK(length(spec_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','VALIDATED')),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE risk_model_version (
  risk_model_version_id TEXT PRIMARY KEY CHECK(risk_model_version_id GLOB 'rmv_*'),
  risk_model_spec_id TEXT NOT NULL REFERENCES risk_model_spec(risk_model_spec_id),
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  universe_version_id TEXT NOT NULL REFERENCES universe_version(universe_version_id),
  exposure_artifact_id TEXT,
  covariance_artifact_id TEXT,
  specific_risk_artifact_id TEXT,
  validation_artifact_id TEXT,
  content_hash TEXT CHECK(content_hash IS NULL OR length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('BUILDING','PUBLISHED','REJECTED')),
  published_at TEXT,
  CHECK(state!='PUBLISHED' OR (exposure_artifact_id IS NOT NULL AND covariance_artifact_id IS NOT NULL AND specific_risk_artifact_id IS NOT NULL AND validation_artifact_id IS NOT NULL))
);

CREATE TABLE constraint_set_version (
  constraint_set_version_id TEXT PRIMARY KEY CHECK(constraint_set_version_id GLOB 'csv_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  compiled_json TEXT NOT NULL CHECK(length(compiled_json)<=65536),
  diagnostics_artifact_id TEXT NOT NULL,
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  published_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE optimization_problem (
  optimization_problem_id TEXT PRIMARY KEY CHECK(optimization_problem_id GLOB 'opb_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  constraint_set_version_id TEXT NOT NULL REFERENCES constraint_set_version(constraint_set_version_id),
  portfolio_version_id TEXT REFERENCES portfolio_version(portfolio_version_id),
  risk_model_version_id TEXT REFERENCES risk_model_version(risk_model_version_id),
  expected_return_artifact_id TEXT,
  problem_json TEXT NOT NULL CHECK(length(problem_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('READY','INVALID')),
  created_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE optimization_solution (
  optimization_solution_id TEXT PRIMARY KEY CHECK(optimization_solution_id GLOB 'ops_*'),
  optimization_problem_id TEXT NOT NULL REFERENCES optimization_problem(optimization_problem_id),
  solver_profile_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OPTIMAL','INFEASIBLE','UNBOUNDED','FAILED','INVALID')),
  weights_artifact_id TEXT,
  solver_log_artifact_id TEXT NOT NULL,
  residual_validation_artifact_id TEXT,
  objective_value_decimal TEXT,
  created_at TEXT NOT NULL,
  CHECK(status!='OPTIMAL' OR (weights_artifact_id IS NOT NULL AND residual_validation_artifact_id IS NOT NULL)),
  CHECK(status='OPTIMAL' OR weights_artifact_id IS NULL)
);

CREATE TABLE experiment (
  experiment_id TEXT PRIMARY KEY CHECK(experiment_id GLOB 'exp_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  experiment_spec_json TEXT NOT NULL CHECK(length(experiment_spec_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','EXPANDED','RUNNING','PARTIAL','COMPLETED','FAILED','CANCELLED')),
  expansion_manifest_artifact_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id,canonical_hash)
);

CREATE TABLE backtest_run_spec (
  backtest_run_spec_id TEXT PRIMARY KEY CHECK(backtest_run_spec_id GLOB 'brs_*'),
  experiment_id TEXT REFERENCES experiment(experiment_id),
  strategy_version_id TEXT NOT NULL REFERENCES strategy_version(strategy_version_id),
  dataset_version_id TEXT REFERENCES dataset_version(dataset_version_id),
  universe_version_id TEXT NOT NULL REFERENCES universe_version(universe_version_id),
  portfolio_version_id TEXT REFERENCES portfolio_version(portfolio_version_id),
  risk_model_version_id TEXT REFERENCES risk_model_version(risk_model_version_id),
  optimization_solution_id TEXT REFERENCES optimization_solution(optimization_solution_id),
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  execution_adapter_version_id TEXT NOT NULL,
  rules_profile_id TEXT NOT NULL,
  fee_profile_id TEXT NOT NULL,
  environment_profile_id TEXT NOT NULL,
  run_spec_json TEXT NOT NULL CHECK(length(run_spec_json)<=65536),
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  published_at TEXT NOT NULL,
  UNIQUE(canonical_hash)
);

CREATE TABLE task (
  task_id TEXT PRIMARY KEY CHECK(task_id GLOB 'tsk_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  parent_task_id TEXT REFERENCES task(task_id),
  service_name TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  truth_state TEXT NOT NULL CHECK(truth_state IN ('FORMAL','DEMO','UNAVAILABLE')),
  state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','PAUSE_REQUESTED','PAUSED','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED','PARTIAL')),
  state_version INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  terminal_at TEXT
);

CREATE TABLE run (
  run_id TEXT PRIMARY KEY CHECK(run_id GLOB 'run_*'),
  task_id TEXT NOT NULL REFERENCES task(task_id),
  run_no INTEGER NOT NULL CHECK(run_no>=1),
  project_context_revision_id TEXT NOT NULL REFERENCES project_context_revision(project_context_revision_id),
  canonical_input_json TEXT NOT NULL CHECK(length(canonical_input_json)<=65536),
  input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
  code_version TEXT NOT NULL,
  environment_profile_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('SEALED','ACTIVE','TERMINAL')),
  created_at TEXT NOT NULL,
  terminal_at TEXT,
  UNIQUE(task_id,run_no),
  UNIQUE(task_id,input_hash,code_version,environment_profile_id)
);

CREATE TABLE task_attempt (
  attempt_id TEXT PRIMARY KEY CHECK(attempt_id GLOB 'att_*'),
  run_id TEXT NOT NULL REFERENCES run(run_id),
  attempt_no INTEGER NOT NULL CHECK(attempt_no>=1),
  retry_of_attempt_id TEXT REFERENCES task_attempt(attempt_id),
  resume_checkpoint_artifact_id TEXT,
  worker_id TEXT,
  lease_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('QUEUED','LEASED','STARTING','RUNNING','CHECKPOINTING','SUCCEEDED','FAILED','CANCELLED','LOST')),
  error_code TEXT,
  error_detail_artifact_id TEXT,
  started_at TEXT,
  heartbeat_at TEXT,
  finished_at TEXT,
  UNIQUE(run_id,attempt_no)
);

CREATE TABLE task_dependency (
  task_id TEXT NOT NULL REFERENCES task(task_id),
  depends_on_task_id TEXT NOT NULL REFERENCES task(task_id),
  required_terminal_state TEXT NOT NULL CHECK(required_terminal_state IN ('SUCCEEDED','TERMINAL_ANY')),
  PRIMARY KEY(task_id,depends_on_task_id),
  CHECK(task_id<>depends_on_task_id)
);

CREATE TABLE task_event (
  task_event_id TEXT PRIMARY KEY CHECK(task_event_id GLOB 'tev_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  project_sequence INTEGER NOT NULL CHECK(project_sequence>=1),
  task_id TEXT NOT NULL REFERENCES task(task_id),
  run_id TEXT REFERENCES run(run_id),
  attempt_id TEXT REFERENCES task_attempt(attempt_id),
  event_type TEXT NOT NULL,
  event_version INTEGER NOT NULL DEFAULT 1 CHECK(event_version>=1),
  payload_json TEXT NOT NULL CHECK(length(payload_json)<=65536),
  occurred_at TEXT NOT NULL,
  persisted_at TEXT NOT NULL,
  UNIQUE(project_id,project_sequence)
);

CREATE TABLE idempotency_record (
  scope_key TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES project(project_id),
  canonical_request_hash TEXT NOT NULL CHECK(length(canonical_request_hash)=64),
  outcome_kind TEXT NOT NULL CHECK(outcome_kind IN ('RESPONSE','TASK_ACCEPTED','ERROR')),
  outcome_json TEXT NOT NULL CHECK(length(outcome_json)<=65536),
  created_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE TABLE checkpoint (
  checkpoint_id TEXT PRIMARY KEY CHECK(checkpoint_id GLOB 'chk_*'),
  attempt_id TEXT NOT NULL REFERENCES task_attempt(attempt_id),
  ordinal INTEGER NOT NULL CHECK(ordinal>=1),
  artifact_id TEXT NOT NULL,
  code_version TEXT NOT NULL,
  environment_profile_id TEXT NOT NULL,
  input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
  compatibility_hash TEXT NOT NULL CHECK(length(compatibility_hash)=64),
  created_at TEXT NOT NULL,
  UNIQUE(attempt_id,ordinal)
);

CREATE TABLE result (
  result_id TEXT PRIMARY KEY CHECK(result_id GLOB 'res_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  backtest_run_id TEXT NOT NULL REFERENCES run(run_id),
  ledger_manifest_artifact_id TEXT NOT NULL,
  reconciliation_artifact_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('PENDING_RECONCILIATION','VALID','INVALID')),
  invalid_reason_code TEXT,
  lineage_hash TEXT NOT NULL CHECK(length(lineage_hash)=64),
  created_at TEXT NOT NULL,
  finalized_at TEXT,
  CHECK(state!='VALID' OR (reconciliation_artifact_id IS NOT NULL AND finalized_at IS NOT NULL)),
  UNIQUE(backtest_run_id)
);

CREATE TABLE result_component (
  result_id TEXT NOT NULL REFERENCES result(result_id),
  component_role TEXT NOT NULL CHECK(component_role IN ('ORDERS','FILLS','POSITIONS','CASH','FEES','NAV','BENCHMARK','METRICS','ATTRIBUTION','RISK','STRESS','WALK_FORWARD','SENSITIVITY','DIAGNOSTICS')),
  artifact_id TEXT NOT NULL,
  schema_fingerprint TEXT,
  PRIMARY KEY(result_id,component_role)
);

CREATE TABLE artifact (
  artifact_id TEXT PRIMARY KEY CHECK(artifact_id GLOB 'art_sha256_*'),
  sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256)=64),
  byte_size INTEGER NOT NULL CHECK(byte_size>=0),
  media_type TEXT NOT NULL,
  semantic_role TEXT NOT NULL,
  storage_key TEXT NOT NULL UNIQUE,
  safe_format_id TEXT,
  schema_fingerprint TEXT,
  state TEXT NOT NULL CHECK(state IN ('STAGED','PUBLISHED','QUARANTINED','DELETED')),
  created_at TEXT NOT NULL,
  published_at TEXT,
  deleted_at TEXT,
  CHECK(state!='PUBLISHED' OR published_at IS NOT NULL)
);

CREATE TABLE artifact_reference (
  artifact_reference_id TEXT PRIMARY KEY CHECK(artifact_reference_id GLOB 'arf_*'),
  owner_type TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  role TEXT NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  state TEXT NOT NULL CHECK(state IN ('ACTIVE','RELEASED')),
  created_at TEXT NOT NULL,
  released_at TEXT,
  UNIQUE(owner_type,owner_id,role,artifact_id)
);

CREATE TABLE worker (
  worker_id TEXT PRIMARY KEY CHECK(worker_id GLOB 'wrk_*'),
  worker_kind TEXT NOT NULL,
  process_id INTEGER,
  environment_profile_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('STARTING','IDLE','BUSY','DRAINING','STOPPED','LOST')),
  started_at TEXT NOT NULL,
  heartbeat_at TEXT,
  stopped_at TEXT
);

CREATE TABLE worker_lease (
  lease_id TEXT PRIMARY KEY CHECK(lease_id GLOB 'lea_*'),
  attempt_id TEXT NOT NULL REFERENCES task_attempt(attempt_id),
  worker_id TEXT NOT NULL REFERENCES worker(worker_id),
  cpu_slots INTEGER NOT NULL CHECK(cpu_slots>=1),
  memory_limit_bytes INTEGER NOT NULL CHECK(memory_limit_bytes>0),
  gpu_device TEXT,
  scratch_limit_bytes INTEGER NOT NULL CHECK(scratch_limit_bytes>=0),
  state TEXT NOT NULL CHECK(state IN ('GRANTED','RENEWED','EXPIRED','RELEASED','REVOKED')),
  granted_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  renewed_at TEXT,
  released_at TEXT
);

CREATE TABLE resource_event (
  resource_event_id TEXT PRIMARY KEY CHECK(resource_event_id GLOB 'rse_*'),
  worker_id TEXT REFERENCES worker(worker_id),
  lease_id TEXT REFERENCES worker_lease(lease_id),
  attempt_id TEXT REFERENCES task_attempt(attempt_id),
  event_type TEXT NOT NULL CHECK(event_type IN ('SAMPLE','PRESSURE','CONCURRENCY_REDUCED','SPILL_REQUESTED','ADMISSION_PAUSED','LIMIT_EXCEEDED','TERMINATE_REQUESTED','OOM','LEASE_EXPIRED')),
  memory_bytes INTEGER,
  cpu_percent_decimal TEXT,
  scratch_bytes INTEGER,
  detail_json TEXT CHECK(detail_json IS NULL OR length(detail_json)<=32768),
  occurred_at TEXT NOT NULL
);

CREATE TABLE provenance_entity (
  provenance_entity_id TEXT PRIMARY KEY CHECK(provenance_entity_id GLOB 'prv_*'),
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  subject_version TEXT,
  canonical_hash TEXT NOT NULL CHECK(length(canonical_hash)=64),
  code_version TEXT,
  environment_profile_id TEXT,
  actor TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  UNIQUE(subject_type,subject_id,canonical_hash)
);

CREATE TABLE provenance_edge (
  provenance_edge_id TEXT PRIMARY KEY CHECK(provenance_edge_id GLOB 'pre_*'),
  from_entity_id TEXT NOT NULL REFERENCES provenance_entity(provenance_entity_id),
  relation TEXT NOT NULL CHECK(relation IN ('USED','GENERATED_BY','DERIVED_FROM','REVISION_OF','VALIDATED_BY','PUBLISHED_AS','EXECUTED_WITH')),
  to_entity_id TEXT NOT NULL REFERENCES provenance_entity(provenance_entity_id),
  recorded_at TEXT NOT NULL,
  UNIQUE(from_entity_id,relation,to_entity_id),
  CHECK(from_entity_id<>to_entity_id)
);

CREATE INDEX idx_project_context_current ON project_context_revision(project_id,revision_no DESC);
CREATE INDEX idx_connector_capability_truth ON connector_capability(capability_code,admitted_truth_state);
CREATE INDEX idx_alias_resolve ON instrument_alias(connector_version_id,provider_code,effective_from,effective_to);
CREATE INDEX idx_instrument_revision_pit ON instrument_revision(instrument_id,effective_from,available_time);
CREATE INDEX idx_raw_capture_range ON raw_capture(connector_version_id,provider_dataset,effective_range_start,effective_range_end);
CREATE INDEX idx_snapshot_state ON data_snapshot(state,published_at);
CREATE INDEX idx_industry_membership_pit ON industry_membership(instrument_id,effective_from,available_time);
CREATE INDEX idx_universe_snapshot ON universe_version(snapshot_id,knowledge_cutoff,state);
CREATE INDEX idx_dataset_inputs ON dataset_version(snapshot_id,universe_version_id,state);
CREATE INDEX idx_trial_study_state ON trial(study_id,state,trial_no);
CREATE INDEX idx_task_project_state ON task(project_id,state,updated_at,task_id);
CREATE INDEX idx_run_task ON run(task_id,run_no);
CREATE INDEX idx_attempt_run ON task_attempt(run_id,attempt_no);
CREATE INDEX idx_event_replay ON task_event(project_id,project_sequence);
CREATE INDEX idx_artifact_ref_target ON artifact_reference(artifact_id,state);
CREATE INDEX idx_worker_heartbeat ON worker(state,heartbeat_at);
CREATE INDEX idx_lease_expiry ON worker_lease(state,expires_at);
CREATE UNIQUE INDEX ux_active_lease_per_attempt ON worker_lease(attempt_id) WHERE state IN ('GRANTED','RENEWED');
CREATE INDEX idx_resource_attempt ON resource_event(attempt_id,occurred_at);
CREATE INDEX idx_provenance_subject ON provenance_entity(subject_type,subject_id);
CREATE INDEX idx_provenance_to ON provenance_edge(to_entity_id,relation);

-- WS-B implementation constraints required by 002_schema_notes.md.
CREATE TRIGGER trg_connector_version_bounded_json_i
BEFORE INSERT ON connector_version
WHEN (NEW.declared_manifest_json IS NOT NULL AND (json_valid(NEW.declared_manifest_json)=0 OR length(CAST(NEW.declared_manifest_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_connector_version_bounded_json_u
BEFORE UPDATE ON connector_version
WHEN (NEW.declared_manifest_json IS NOT NULL AND (json_valid(NEW.declared_manifest_json)=0 OR length(CAST(NEW.declared_manifest_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_connector_capability_bounded_json_i
BEFORE INSERT ON connector_capability
WHEN (NEW.limitation_json IS NOT NULL AND (json_valid(NEW.limitation_json)=0 OR length(CAST(NEW.limitation_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_connector_capability_bounded_json_u
BEFORE UPDATE ON connector_capability
WHEN (NEW.limitation_json IS NOT NULL AND (json_valid(NEW.limitation_json)=0 OR length(CAST(NEW.limitation_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_project_context_revision_bounded_json_i
BEFORE INSERT ON project_context_revision
WHEN (NEW.context_json IS NOT NULL AND (json_valid(NEW.context_json)=0 OR length(CAST(NEW.context_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_project_context_revision_bounded_json_u
BEFORE UPDATE ON project_context_revision
WHEN (NEW.context_json IS NOT NULL AND (json_valid(NEW.context_json)=0 OR length(CAST(NEW.context_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_instrument_revision_bounded_json_i
BEFORE INSERT ON instrument_revision
WHEN (NEW.lifecycle_json IS NOT NULL AND (json_valid(NEW.lifecycle_json)=0 OR length(CAST(NEW.lifecycle_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_instrument_revision_bounded_json_u
BEFORE UPDATE ON instrument_revision
WHEN (NEW.lifecycle_json IS NOT NULL AND (json_valid(NEW.lifecycle_json)=0 OR length(CAST(NEW.lifecycle_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_universe_definition_bounded_json_i
BEFORE INSERT ON universe_definition
WHEN (NEW.definition_json IS NOT NULL AND (json_valid(NEW.definition_json)=0 OR length(CAST(NEW.definition_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_universe_definition_bounded_json_u
BEFORE UPDATE ON universe_definition
WHEN (NEW.definition_json IS NOT NULL AND (json_valid(NEW.definition_json)=0 OR length(CAST(NEW.definition_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_factor_definition_bounded_json_i
BEFORE INSERT ON factor_definition
WHEN (NEW.definition_json IS NOT NULL AND (json_valid(NEW.definition_json)=0 OR length(CAST(NEW.definition_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_factor_definition_bounded_json_u
BEFORE UPDATE ON factor_definition
WHEN (NEW.definition_json IS NOT NULL AND (json_valid(NEW.definition_json)=0 OR length(CAST(NEW.definition_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_factor_version_bounded_json_i
BEFORE INSERT ON factor_version
WHEN (NEW.availability_policy_json IS NOT NULL AND (json_valid(NEW.availability_policy_json)=0 OR length(CAST(NEW.availability_policy_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_factor_version_bounded_json_u
BEFORE UPDATE ON factor_version
WHEN (NEW.availability_policy_json IS NOT NULL AND (json_valid(NEW.availability_policy_json)=0 OR length(CAST(NEW.availability_policy_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_dataset_spec_bounded_json_i
BEFORE INSERT ON dataset_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_dataset_spec_bounded_json_u
BEFORE UPDATE ON dataset_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_model_spec_bounded_json_i
BEFORE INSERT ON model_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_model_spec_bounded_json_u
BEFORE UPDATE ON model_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_study_bounded_json_i
BEFORE INSERT ON study
WHEN (NEW.study_spec_json IS NOT NULL AND (json_valid(NEW.study_spec_json)=0 OR length(CAST(NEW.study_spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_study_bounded_json_u
BEFORE UPDATE ON study
WHEN (NEW.study_spec_json IS NOT NULL AND (json_valid(NEW.study_spec_json)=0 OR length(CAST(NEW.study_spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_trial_bounded_json_i
BEFORE INSERT ON trial
WHEN (NEW.parameter_json IS NOT NULL AND (json_valid(NEW.parameter_json)=0 OR length(CAST(NEW.parameter_json AS BLOB))>65536)) OR (NEW.objective_summary_json IS NOT NULL AND (json_valid(NEW.objective_summary_json)=0 OR length(CAST(NEW.objective_summary_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_trial_bounded_json_u
BEFORE UPDATE ON trial
WHEN (NEW.parameter_json IS NOT NULL AND (json_valid(NEW.parameter_json)=0 OR length(CAST(NEW.parameter_json AS BLOB))>65536)) OR (NEW.objective_summary_json IS NOT NULL AND (json_valid(NEW.objective_summary_json)=0 OR length(CAST(NEW.objective_summary_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_portfolio_construction_spec_bounded_json_i
BEFORE INSERT ON portfolio_construction_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_portfolio_construction_spec_bounded_json_u
BEFORE UPDATE ON portfolio_construction_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_risk_model_spec_bounded_json_i
BEFORE INSERT ON risk_model_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_risk_model_spec_bounded_json_u
BEFORE UPDATE ON risk_model_spec
WHEN (NEW.spec_json IS NOT NULL AND (json_valid(NEW.spec_json)=0 OR length(CAST(NEW.spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_constraint_set_version_bounded_json_i
BEFORE INSERT ON constraint_set_version
WHEN (NEW.compiled_json IS NOT NULL AND (json_valid(NEW.compiled_json)=0 OR length(CAST(NEW.compiled_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_constraint_set_version_bounded_json_u
BEFORE UPDATE ON constraint_set_version
WHEN (NEW.compiled_json IS NOT NULL AND (json_valid(NEW.compiled_json)=0 OR length(CAST(NEW.compiled_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_optimization_problem_bounded_json_i
BEFORE INSERT ON optimization_problem
WHEN (NEW.problem_json IS NOT NULL AND (json_valid(NEW.problem_json)=0 OR length(CAST(NEW.problem_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_optimization_problem_bounded_json_u
BEFORE UPDATE ON optimization_problem
WHEN (NEW.problem_json IS NOT NULL AND (json_valid(NEW.problem_json)=0 OR length(CAST(NEW.problem_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_experiment_bounded_json_i
BEFORE INSERT ON experiment
WHEN (NEW.experiment_spec_json IS NOT NULL AND (json_valid(NEW.experiment_spec_json)=0 OR length(CAST(NEW.experiment_spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_experiment_bounded_json_u
BEFORE UPDATE ON experiment
WHEN (NEW.experiment_spec_json IS NOT NULL AND (json_valid(NEW.experiment_spec_json)=0 OR length(CAST(NEW.experiment_spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_backtest_run_spec_bounded_json_i
BEFORE INSERT ON backtest_run_spec
WHEN (NEW.run_spec_json IS NOT NULL AND (json_valid(NEW.run_spec_json)=0 OR length(CAST(NEW.run_spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_backtest_run_spec_bounded_json_u
BEFORE UPDATE ON backtest_run_spec
WHEN (NEW.run_spec_json IS NOT NULL AND (json_valid(NEW.run_spec_json)=0 OR length(CAST(NEW.run_spec_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_run_bounded_json_i
BEFORE INSERT ON run
WHEN (NEW.canonical_input_json IS NOT NULL AND (json_valid(NEW.canonical_input_json)=0 OR length(CAST(NEW.canonical_input_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_run_bounded_json_u
BEFORE UPDATE ON run
WHEN (NEW.canonical_input_json IS NOT NULL AND (json_valid(NEW.canonical_input_json)=0 OR length(CAST(NEW.canonical_input_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_task_event_bounded_json_i
BEFORE INSERT ON task_event
WHEN (NEW.payload_json IS NOT NULL AND (json_valid(NEW.payload_json)=0 OR length(CAST(NEW.payload_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_task_event_bounded_json_u
BEFORE UPDATE ON task_event
WHEN (NEW.payload_json IS NOT NULL AND (json_valid(NEW.payload_json)=0 OR length(CAST(NEW.payload_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_idempotency_record_bounded_json_i
BEFORE INSERT ON idempotency_record
WHEN (NEW.outcome_json IS NOT NULL AND (json_valid(NEW.outcome_json)=0 OR length(CAST(NEW.outcome_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_idempotency_record_bounded_json_u
BEFORE UPDATE ON idempotency_record
WHEN (NEW.outcome_json IS NOT NULL AND (json_valid(NEW.outcome_json)=0 OR length(CAST(NEW.outcome_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_resource_event_bounded_json_i
BEFORE INSERT ON resource_event
WHEN (NEW.detail_json IS NOT NULL AND (json_valid(NEW.detail_json)=0 OR length(CAST(NEW.detail_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_resource_event_bounded_json_u
BEFORE UPDATE ON resource_event
WHEN (NEW.detail_json IS NOT NULL AND (json_valid(NEW.detail_json)=0 OR length(CAST(NEW.detail_json AS BLOB))>65536))
BEGIN
  SELECT RAISE(ABORT,'Catalog JSON must be valid and at most 64 KiB');
END;

CREATE TRIGGER trg_connector_version_published_artifact_i
BEFORE INSERT ON connector_version
WHEN (NEW.bundle_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.bundle_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_connector_version_published_artifact_u
BEFORE UPDATE ON connector_version
WHEN (NEW.bundle_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.bundle_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_connector_capability_published_artifact_i
BEFORE INSERT ON connector_capability
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_connector_capability_published_artifact_u
BEFORE UPDATE ON connector_capability
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_connector_admission_published_artifact_i
BEFORE INSERT ON connector_admission
WHEN (NEW.report_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.report_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_connector_admission_published_artifact_u
BEFORE UPDATE ON connector_admission
WHEN (NEW.report_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.report_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_data_snapshot_published_artifact_i
BEFORE INSERT ON data_snapshot
WHEN (NEW.manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_data_snapshot_published_artifact_u
BEFORE UPDATE ON data_snapshot
WHEN (NEW.manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_desktop_session_published_artifact_i
BEFORE INSERT ON desktop_session
WHEN (NEW.layout_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.layout_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_desktop_session_published_artifact_u
BEFORE UPDATE ON desktop_session
WHEN (NEW.layout_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.layout_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_instrument_revision_published_artifact_i
BEFORE INSERT ON instrument_revision
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_instrument_revision_published_artifact_u
BEFORE UPDATE ON instrument_revision
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_instrument_alias_published_artifact_i
BEFORE INSERT ON instrument_alias
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_instrument_alias_published_artifact_u
BEFORE UPDATE ON instrument_alias
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_raw_capture_published_artifact_i
BEFORE INSERT ON raw_capture
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_raw_capture_published_artifact_u
BEFORE UPDATE ON raw_capture
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_snapshot_partition_published_artifact_i
BEFORE INSERT ON snapshot_partition
WHEN (NEW.parquet_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.parquet_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_snapshot_partition_published_artifact_u
BEFORE UPDATE ON snapshot_partition
WHEN (NEW.parquet_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.parquet_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_snapshot_validation_published_artifact_i
BEFORE INSERT ON snapshot_validation
WHEN (NEW.report_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.report_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_snapshot_validation_published_artifact_u
BEFORE UPDATE ON snapshot_validation
WHEN (NEW.report_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.report_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_industry_taxonomy_version_published_artifact_i
BEFORE INSERT ON industry_taxonomy_version
WHEN (NEW.manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_industry_taxonomy_version_published_artifact_u
BEFORE UPDATE ON industry_taxonomy_version
WHEN (NEW.manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_industry_membership_published_artifact_i
BEFORE INSERT ON industry_membership
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_industry_membership_published_artifact_u
BEFORE UPDATE ON industry_membership
WHEN (NEW.evidence_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_universe_version_published_artifact_i
BEFORE INSERT ON universe_version
WHEN (NEW.membership_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.membership_artifact_id AND state='PUBLISHED')) OR (NEW.audit_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.audit_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_universe_version_published_artifact_u
BEFORE UPDATE ON universe_version
WHEN (NEW.membership_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.membership_artifact_id AND state='PUBLISHED')) OR (NEW.audit_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.audit_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_factor_version_published_artifact_i
BEFORE INSERT ON factor_version
WHEN (NEW.code_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.code_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_factor_version_published_artifact_u
BEFORE UPDATE ON factor_version
WHEN (NEW.code_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.code_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_dataset_spec_published_artifact_i
BEFORE INSERT ON dataset_spec
WHEN (NEW.validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_dataset_spec_published_artifact_u
BEFORE UPDATE ON dataset_spec
WHEN (NEW.validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_dataset_version_published_artifact_i
BEFORE INSERT ON dataset_version
WHEN (NEW.manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED')) OR (NEW.leakage_audit_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.leakage_audit_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_dataset_version_published_artifact_u
BEFORE UPDATE ON dataset_version
WHEN (NEW.manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED')) OR (NEW.leakage_audit_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.leakage_audit_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_strategy_draft_published_artifact_i
BEFORE INSERT ON strategy_draft
WHEN (NEW.draft_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.draft_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_strategy_draft_published_artifact_u
BEFORE UPDATE ON strategy_draft
WHEN (NEW.draft_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.draft_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_strategy_version_published_artifact_i
BEFORE INSERT ON strategy_version
WHEN (NEW.strategy_ir_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.strategy_ir_artifact_id AND state='PUBLISHED')) OR (NEW.validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_strategy_version_published_artifact_u
BEFORE UPDATE ON strategy_version
WHEN (NEW.strategy_ir_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.strategy_ir_artifact_id AND state='PUBLISHED')) OR (NEW.validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_model_version_published_artifact_i
BEFORE INSERT ON model_version
WHEN (NEW.model_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.model_artifact_id AND state='PUBLISHED')) OR (NEW.metrics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.metrics_artifact_id AND state='PUBLISHED')) OR (NEW.model_card_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.model_card_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_model_version_published_artifact_u
BEFORE UPDATE ON model_version
WHEN (NEW.model_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.model_artifact_id AND state='PUBLISHED')) OR (NEW.metrics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.metrics_artifact_id AND state='PUBLISHED')) OR (NEW.model_card_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.model_card_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_prediction_signal_version_published_artifact_i
BEFORE INSERT ON prediction_signal_version
WHEN (NEW.signal_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.signal_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_prediction_signal_version_published_artifact_u
BEFORE UPDATE ON prediction_signal_version
WHEN (NEW.signal_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.signal_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_trial_published_artifact_i
BEFORE INSERT ON trial
WHEN (NEW.metrics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.metrics_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_trial_published_artifact_u
BEFORE UPDATE ON trial
WHEN (NEW.metrics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.metrics_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_portfolio_version_published_artifact_i
BEFORE INSERT ON portfolio_version
WHEN (NEW.targets_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.targets_artifact_id AND state='PUBLISHED')) OR (NEW.diagnostics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.diagnostics_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_portfolio_version_published_artifact_u
BEFORE UPDATE ON portfolio_version
WHEN (NEW.targets_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.targets_artifact_id AND state='PUBLISHED')) OR (NEW.diagnostics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.diagnostics_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_risk_model_version_published_artifact_i
BEFORE INSERT ON risk_model_version
WHEN (NEW.exposure_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.exposure_artifact_id AND state='PUBLISHED')) OR (NEW.covariance_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.covariance_artifact_id AND state='PUBLISHED')) OR (NEW.specific_risk_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.specific_risk_artifact_id AND state='PUBLISHED')) OR (NEW.validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_risk_model_version_published_artifact_u
BEFORE UPDATE ON risk_model_version
WHEN (NEW.exposure_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.exposure_artifact_id AND state='PUBLISHED')) OR (NEW.covariance_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.covariance_artifact_id AND state='PUBLISHED')) OR (NEW.specific_risk_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.specific_risk_artifact_id AND state='PUBLISHED')) OR (NEW.validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_constraint_set_version_published_artifact_i
BEFORE INSERT ON constraint_set_version
WHEN (NEW.diagnostics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.diagnostics_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_constraint_set_version_published_artifact_u
BEFORE UPDATE ON constraint_set_version
WHEN (NEW.diagnostics_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.diagnostics_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_optimization_problem_published_artifact_i
BEFORE INSERT ON optimization_problem
WHEN (NEW.expected_return_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.expected_return_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_optimization_problem_published_artifact_u
BEFORE UPDATE ON optimization_problem
WHEN (NEW.expected_return_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.expected_return_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_optimization_solution_published_artifact_i
BEFORE INSERT ON optimization_solution
WHEN (NEW.weights_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.weights_artifact_id AND state='PUBLISHED')) OR (NEW.solver_log_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.solver_log_artifact_id AND state='PUBLISHED')) OR (NEW.residual_validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.residual_validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_optimization_solution_published_artifact_u
BEFORE UPDATE ON optimization_solution
WHEN (NEW.weights_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.weights_artifact_id AND state='PUBLISHED')) OR (NEW.solver_log_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.solver_log_artifact_id AND state='PUBLISHED')) OR (NEW.residual_validation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.residual_validation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_experiment_published_artifact_i
BEFORE INSERT ON experiment
WHEN (NEW.expansion_manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.expansion_manifest_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_experiment_published_artifact_u
BEFORE UPDATE ON experiment
WHEN (NEW.expansion_manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.expansion_manifest_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_task_attempt_published_artifact_i
BEFORE INSERT ON task_attempt
WHEN (NEW.resume_checkpoint_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.resume_checkpoint_artifact_id AND state='PUBLISHED')) OR (NEW.error_detail_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.error_detail_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_task_attempt_published_artifact_u
BEFORE UPDATE ON task_attempt
WHEN (NEW.resume_checkpoint_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.resume_checkpoint_artifact_id AND state='PUBLISHED')) OR (NEW.error_detail_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.error_detail_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_checkpoint_published_artifact_i
BEFORE INSERT ON checkpoint
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_checkpoint_published_artifact_u
BEFORE UPDATE ON checkpoint
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_result_published_artifact_i
BEFORE INSERT ON result
WHEN (NEW.ledger_manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.ledger_manifest_artifact_id AND state='PUBLISHED')) OR (NEW.reconciliation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.reconciliation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_result_published_artifact_u
BEFORE UPDATE ON result
WHEN (NEW.ledger_manifest_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.ledger_manifest_artifact_id AND state='PUBLISHED')) OR (NEW.reconciliation_artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.reconciliation_artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_result_component_published_artifact_i
BEFORE INSERT ON result_component
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_result_component_published_artifact_u
BEFORE UPDATE ON result_component
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_artifact_reference_published_artifact_i
BEFORE INSERT ON artifact_reference
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_artifact_reference_published_artifact_u
BEFORE UPDATE ON artifact_reference
WHEN (NEW.artifact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED'))
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_project_context_revision_append_only_u
BEFORE UPDATE ON project_context_revision
BEGIN
  SELECT RAISE(ABORT,'project_context_revision is append-only');
END;

CREATE TRIGGER trg_project_context_revision_append_only_d
BEFORE DELETE ON project_context_revision
BEGIN
  SELECT RAISE(ABORT,'project_context_revision is append-only');
END;

CREATE TRIGGER trg_instrument_revision_append_only_u
BEFORE UPDATE ON instrument_revision
BEGIN
  SELECT RAISE(ABORT,'instrument_revision is append-only');
END;

CREATE TRIGGER trg_instrument_revision_append_only_d
BEFORE DELETE ON instrument_revision
BEGIN
  SELECT RAISE(ABORT,'instrument_revision is append-only');
END;

CREATE TRIGGER trg_instrument_alias_append_only_u
BEFORE UPDATE ON instrument_alias
BEGIN
  SELECT RAISE(ABORT,'instrument_alias is append-only');
END;

CREATE TRIGGER trg_instrument_alias_append_only_d
BEFORE DELETE ON instrument_alias
BEGIN
  SELECT RAISE(ABORT,'instrument_alias is append-only');
END;

CREATE TRIGGER trg_snapshot_partition_append_only_u
BEFORE UPDATE ON snapshot_partition
BEGIN
  SELECT RAISE(ABORT,'snapshot_partition is append-only');
END;

CREATE TRIGGER trg_snapshot_partition_append_only_d
BEFORE DELETE ON snapshot_partition
BEGIN
  SELECT RAISE(ABORT,'snapshot_partition is append-only');
END;

CREATE TRIGGER trg_snapshot_validation_append_only_u
BEFORE UPDATE ON snapshot_validation
BEGIN
  SELECT RAISE(ABORT,'snapshot_validation is append-only');
END;

CREATE TRIGGER trg_snapshot_validation_append_only_d
BEFORE DELETE ON snapshot_validation
BEGIN
  SELECT RAISE(ABORT,'snapshot_validation is append-only');
END;

CREATE TRIGGER trg_industry_taxonomy_version_append_only_u
BEFORE UPDATE ON industry_taxonomy_version
BEGIN
  SELECT RAISE(ABORT,'industry_taxonomy_version is append-only');
END;

CREATE TRIGGER trg_industry_taxonomy_version_append_only_d
BEFORE DELETE ON industry_taxonomy_version
BEGIN
  SELECT RAISE(ABORT,'industry_taxonomy_version is append-only');
END;

CREATE TRIGGER trg_industry_membership_append_only_u
BEFORE UPDATE ON industry_membership
BEGIN
  SELECT RAISE(ABORT,'industry_membership is append-only');
END;

CREATE TRIGGER trg_industry_membership_append_only_d
BEFORE DELETE ON industry_membership
BEGIN
  SELECT RAISE(ABORT,'industry_membership is append-only');
END;

CREATE TRIGGER trg_constraint_set_version_append_only_u
BEFORE UPDATE ON constraint_set_version
BEGIN
  SELECT RAISE(ABORT,'constraint_set_version is append-only');
END;

CREATE TRIGGER trg_constraint_set_version_append_only_d
BEFORE DELETE ON constraint_set_version
BEGIN
  SELECT RAISE(ABORT,'constraint_set_version is append-only');
END;

CREATE TRIGGER trg_optimization_solution_append_only_u
BEFORE UPDATE ON optimization_solution
BEGIN
  SELECT RAISE(ABORT,'optimization_solution is append-only');
END;

CREATE TRIGGER trg_optimization_solution_append_only_d
BEFORE DELETE ON optimization_solution
BEGIN
  SELECT RAISE(ABORT,'optimization_solution is append-only');
END;

CREATE TRIGGER trg_backtest_run_spec_append_only_u
BEFORE UPDATE ON backtest_run_spec
BEGIN
  SELECT RAISE(ABORT,'backtest_run_spec is append-only');
END;

CREATE TRIGGER trg_backtest_run_spec_append_only_d
BEFORE DELETE ON backtest_run_spec
BEGIN
  SELECT RAISE(ABORT,'backtest_run_spec is append-only');
END;

CREATE TRIGGER trg_task_dependency_append_only_u
BEFORE UPDATE ON task_dependency
BEGIN
  SELECT RAISE(ABORT,'task_dependency is append-only');
END;

CREATE TRIGGER trg_task_dependency_append_only_d
BEFORE DELETE ON task_dependency
BEGIN
  SELECT RAISE(ABORT,'task_dependency is append-only');
END;

CREATE TRIGGER trg_task_event_append_only_u
BEFORE UPDATE ON task_event
BEGIN
  SELECT RAISE(ABORT,'task_event is append-only');
END;

CREATE TRIGGER trg_task_event_append_only_d
BEFORE DELETE ON task_event
BEGIN
  SELECT RAISE(ABORT,'task_event is append-only');
END;

CREATE TRIGGER trg_idempotency_record_append_only_u
BEFORE UPDATE ON idempotency_record
BEGIN
  SELECT RAISE(ABORT,'idempotency_record is append-only');
END;

CREATE TRIGGER trg_idempotency_record_append_only_d
BEFORE DELETE ON idempotency_record
BEGIN
  SELECT RAISE(ABORT,'idempotency_record is append-only');
END;

CREATE TRIGGER trg_checkpoint_append_only_u
BEFORE UPDATE ON checkpoint
BEGIN
  SELECT RAISE(ABORT,'checkpoint is append-only');
END;

CREATE TRIGGER trg_checkpoint_append_only_d
BEFORE DELETE ON checkpoint
BEGIN
  SELECT RAISE(ABORT,'checkpoint is append-only');
END;

CREATE TRIGGER trg_result_component_append_only_u
BEFORE UPDATE ON result_component
BEGIN
  SELECT RAISE(ABORT,'result_component is append-only');
END;

CREATE TRIGGER trg_result_component_append_only_d
BEFORE DELETE ON result_component
BEGIN
  SELECT RAISE(ABORT,'result_component is append-only');
END;

CREATE TRIGGER trg_provenance_entity_append_only_u
BEFORE UPDATE ON provenance_entity
BEGIN
  SELECT RAISE(ABORT,'provenance_entity is append-only');
END;

CREATE TRIGGER trg_provenance_entity_append_only_d
BEFORE DELETE ON provenance_entity
BEGIN
  SELECT RAISE(ABORT,'provenance_entity is append-only');
END;

CREATE TRIGGER trg_provenance_edge_append_only_u
BEFORE UPDATE ON provenance_edge
BEGIN
  SELECT RAISE(ABORT,'provenance_edge is append-only');
END;

CREATE TRIGGER trg_provenance_edge_append_only_d
BEFORE DELETE ON provenance_edge
BEGIN
  SELECT RAISE(ABORT,'provenance_edge is append-only');
END;

CREATE TRIGGER trg_data_snapshot_published_immutable_u
BEFORE UPDATE ON data_snapshot
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.snapshot_id IS NOT OLD.snapshot_id OR NEW.connector_version_id IS NOT OLD.connector_version_id OR NEW.parent_snapshot_id IS NOT OLD.parent_snapshot_id OR NEW.manifest_artifact_id IS NOT OLD.manifest_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.normalization_spec_version IS NOT OLD.normalization_spec_version OR NEW.truth_profile_id IS NOT OLD.truth_profile_id OR NEW.min_effective_time IS NOT OLD.min_effective_time OR NEW.max_effective_time IS NOT OLD.max_effective_time OR NEW.max_available_time IS NOT OLD.max_available_time OR NEW.created_at IS NOT OLD.created_at OR NEW.validated_at IS NOT OLD.validated_at OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_data_snapshot_no_delete_d
BEFORE DELETE ON data_snapshot
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_universe_definition_published_immutable_u
BEFORE UPDATE ON universe_definition
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.universe_definition_id IS NOT OLD.universe_definition_id OR NEW.project_id IS NOT OLD.project_id OR NEW.constructor_kind IS NOT OLD.constructor_kind OR NEW.definition_json IS NOT OLD.definition_json OR NEW.canonical_hash IS NOT OLD.canonical_hash OR NEW.created_at IS NOT OLD.created_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_universe_definition_no_delete_d
BEFORE DELETE ON universe_definition
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_universe_version_published_immutable_u
BEFORE UPDATE ON universe_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.universe_version_id IS NOT OLD.universe_version_id OR NEW.universe_definition_id IS NOT OLD.universe_definition_id OR NEW.snapshot_id IS NOT OLD.snapshot_id OR NEW.industry_taxonomy_version_id IS NOT OLD.industry_taxonomy_version_id OR NEW.knowledge_cutoff IS NOT OLD.knowledge_cutoff OR NEW.membership_artifact_id IS NOT OLD.membership_artifact_id OR NEW.audit_artifact_id IS NOT OLD.audit_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_universe_version_no_delete_d
BEFORE DELETE ON universe_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_factor_version_published_immutable_u
BEFORE UPDATE ON factor_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.factor_version_id IS NOT OLD.factor_version_id OR NEW.factor_definition_id IS NOT OLD.factor_definition_id OR NEW.semantic_version IS NOT OLD.semantic_version OR NEW.code_artifact_id IS NOT OLD.code_artifact_id OR NEW.code_hash IS NOT OLD.code_hash OR NEW.availability_policy_json IS NOT OLD.availability_policy_json OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_factor_version_no_delete_d
BEFORE DELETE ON factor_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_dataset_version_published_immutable_u
BEFORE UPDATE ON dataset_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.dataset_version_id IS NOT OLD.dataset_version_id OR NEW.dataset_spec_id IS NOT OLD.dataset_spec_id OR NEW.snapshot_id IS NOT OLD.snapshot_id OR NEW.universe_version_id IS NOT OLD.universe_version_id OR NEW.manifest_artifact_id IS NOT OLD.manifest_artifact_id OR NEW.leakage_audit_artifact_id IS NOT OLD.leakage_audit_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_dataset_version_no_delete_d
BEFORE DELETE ON dataset_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_strategy_version_published_immutable_u
BEFORE UPDATE ON strategy_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.strategy_version_id IS NOT OLD.strategy_version_id OR NEW.project_id IS NOT OLD.project_id OR NEW.strategy_ir_artifact_id IS NOT OLD.strategy_ir_artifact_id OR NEW.validation_artifact_id IS NOT OLD.validation_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.compiler_profile_id IS NOT OLD.compiler_profile_id OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_strategy_version_no_delete_d
BEFORE DELETE ON strategy_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_model_version_published_immutable_u
BEFORE UPDATE ON model_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.model_version_id IS NOT OLD.model_version_id OR NEW.model_spec_id IS NOT OLD.model_spec_id OR NEW.dataset_version_id IS NOT OLD.dataset_version_id OR NEW.run_id IS NOT OLD.run_id OR NEW.model_artifact_id IS NOT OLD.model_artifact_id OR NEW.metrics_artifact_id IS NOT OLD.metrics_artifact_id OR NEW.model_card_artifact_id IS NOT OLD.model_card_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.safe_format_id IS NOT OLD.safe_format_id OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_model_version_no_delete_d
BEFORE DELETE ON model_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_prediction_signal_version_published_immutable_u
BEFORE UPDATE ON prediction_signal_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.prediction_signal_version_id IS NOT OLD.prediction_signal_version_id OR NEW.model_version_id IS NOT OLD.model_version_id OR NEW.dataset_version_id IS NOT OLD.dataset_version_id OR NEW.signal_artifact_id IS NOT OLD.signal_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_prediction_signal_version_no_delete_d
BEFORE DELETE ON prediction_signal_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_portfolio_construction_spec_published_immutable_u
BEFORE UPDATE ON portfolio_construction_spec
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.portfolio_spec_id IS NOT OLD.portfolio_spec_id OR NEW.project_id IS NOT OLD.project_id OR NEW.spec_json IS NOT OLD.spec_json OR NEW.canonical_hash IS NOT OLD.canonical_hash OR NEW.created_at IS NOT OLD.created_at OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_portfolio_construction_spec_no_delete_d
BEFORE DELETE ON portfolio_construction_spec
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_portfolio_version_published_immutable_u
BEFORE UPDATE ON portfolio_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.portfolio_version_id IS NOT OLD.portfolio_version_id OR NEW.portfolio_spec_id IS NOT OLD.portfolio_spec_id OR NEW.prediction_signal_version_id IS NOT OLD.prediction_signal_version_id OR NEW.universe_version_id IS NOT OLD.universe_version_id OR NEW.targets_artifact_id IS NOT OLD.targets_artifact_id OR NEW.diagnostics_artifact_id IS NOT OLD.diagnostics_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_portfolio_version_no_delete_d
BEFORE DELETE ON portfolio_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_risk_model_version_published_immutable_u
BEFORE UPDATE ON risk_model_version
WHEN OLD.state='PUBLISHED'
 AND (NEW.state<>'RETIRED' OR NEW.risk_model_version_id IS NOT OLD.risk_model_version_id OR NEW.risk_model_spec_id IS NOT OLD.risk_model_spec_id OR NEW.snapshot_id IS NOT OLD.snapshot_id OR NEW.universe_version_id IS NOT OLD.universe_version_id OR NEW.exposure_artifact_id IS NOT OLD.exposure_artifact_id OR NEW.covariance_artifact_id IS NOT OLD.covariance_artifact_id OR NEW.specific_risk_artifact_id IS NOT OLD.specific_risk_artifact_id OR NEW.validation_artifact_id IS NOT OLD.validation_artifact_id OR NEW.content_hash IS NOT OLD.content_hash OR NEW.published_at IS NOT OLD.published_at)
BEGIN
  SELECT RAISE(ABORT,'published version is immutable');
END;

CREATE TRIGGER trg_risk_model_version_no_delete_d
BEFORE DELETE ON risk_model_version
BEGIN
  SELECT RAISE(ABORT,'version rows cannot be deleted');
END;

CREATE TRIGGER trg_project_context_universe_i
BEFORE INSERT ON project_context_revision
WHEN NEW.universe_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM universe_version WHERE universe_version_id=NEW.universe_version_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'ProjectContext must reference a PUBLISHED UniverseVersion');
END;

CREATE TRIGGER trg_instrument_alias_no_overlap_i
BEFORE INSERT ON instrument_alias
WHEN EXISTS (SELECT 1 FROM instrument_alias AS existing WHERE existing.connector_version_id=NEW.connector_version_id AND existing.provider_code=NEW.provider_code AND (existing.effective_to IS NULL OR existing.effective_to>NEW.effective_from) AND (NEW.effective_to IS NULL OR existing.effective_from<NEW.effective_to))
BEGIN
  SELECT RAISE(ABORT,'provider alias interval overlap');
END;

CREATE TRIGGER trg_run_inputs_sealed_u
BEFORE UPDATE ON run
WHEN NEW.project_context_revision_id IS NOT OLD.project_context_revision_id OR NEW.canonical_input_json IS NOT OLD.canonical_input_json OR NEW.input_hash IS NOT OLD.input_hash OR NEW.code_version IS NOT OLD.code_version OR NEW.environment_profile_id IS NOT OLD.environment_profile_id
BEGIN
  SELECT RAISE(ABORT,'Run inputs are sealed');
END;

CREATE TRIGGER trg_trial_parameters_immutable_u
BEFORE UPDATE ON trial
WHEN NEW.parameter_json IS NOT OLD.parameter_json OR NEW.parameter_hash IS NOT OLD.parameter_hash OR NEW.study_id IS NOT OLD.study_id OR NEW.trial_no IS NOT OLD.trial_no
BEGIN
  SELECT RAISE(ABORT,'Trial parameters are immutable');
END;

CREATE TRIGGER trg_attempt_terminal_immutable_u
BEFORE UPDATE ON task_attempt
WHEN OLD.state IN ('SUCCEEDED','FAILED','CANCELLED','LOST')
BEGIN
  SELECT RAISE(ABORT,'terminal TaskAttempt is immutable');
END;

CREATE TRIGGER trg_attempt_no_delete_d
BEFORE DELETE ON task_attempt
BEGIN
  SELECT RAISE(ABORT,'TaskAttempt rows cannot be deleted');
END;

CREATE TRIGGER trg_result_terminal_immutable_u
BEFORE UPDATE ON result
WHEN OLD.state IN ('VALID','INVALID')
BEGIN
  SELECT RAISE(ABORT,'terminal Result is immutable');
END;

CREATE TRIGGER trg_result_no_delete_d
BEFORE DELETE ON result
BEGIN
  SELECT RAISE(ABORT,'Result rows cannot be deleted');
END;

PRAGMA user_version = 1;
