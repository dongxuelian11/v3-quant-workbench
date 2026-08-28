-- PR03: durable runtime execution identity, queue controls, progress and receipts.
-- Existing Task/Run/Attempt state constraints remain unchanged.  The
-- supplemental tables hold control-plane fields that do not belong in the
-- frozen domain dataclasses.

CREATE TABLE runtime_generation (
  runtime_generation_id TEXT PRIMARY KEY CHECK(length(runtime_generation_id) BETWEEN 4 AND 128),
  process_identity_hash TEXT NOT NULL CHECK(
    length(process_identity_hash)=64
    AND process_identity_hash=lower(process_identity_hash)
    AND process_identity_hash NOT GLOB '*[^0-9a-f]*'
  ),
  started_at TEXT NOT NULL,
  clean_shutdown_at TEXT,
  CHECK(clean_shutdown_at IS NULL OR julianday(clean_shutdown_at) IS NOT NULL)
);

ALTER TABLE run ADD COLUMN operation_schema_version TEXT NOT NULL DEFAULT '1.0.0'
  CHECK(length(operation_schema_version) BETWEEN 1 AND 128);
ALTER TABLE run ADD COLUMN resource_policy_version TEXT NOT NULL DEFAULT '1.0.0'
  CHECK(length(resource_policy_version) BETWEEN 1 AND 128);
ALTER TABLE run ADD COLUMN resolved_resource_json TEXT NOT NULL DEFAULT '{}'
  CHECK(json_valid(resolved_resource_json) AND length(CAST(resolved_resource_json AS BLOB))<=65536);
ALTER TABLE run ADD COLUMN resolved_resource_hash TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000'
  CHECK(
    length(resolved_resource_hash)=64
    AND resolved_resource_hash=lower(resolved_resource_hash)
    AND resolved_resource_hash NOT GLOB '*[^0-9a-f]*'
  );
ALTER TABLE run ADD COLUMN compatibility_hash TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000'
  CHECK(
    length(compatibility_hash)=64
    AND compatibility_hash=lower(compatibility_hash)
    AND compatibility_hash NOT GLOB '*[^0-9a-f]*'
  );

ALTER TABLE task_attempt ADD COLUMN runtime_generation_id TEXT
  REFERENCES runtime_generation(runtime_generation_id);
ALTER TABLE task_attempt ADD COLUMN interruption_reason TEXT
  CHECK(interruption_reason IS NULL OR length(interruption_reason) BETWEEN 1 AND 128);
ALTER TABLE task_attempt ADD COLUMN last_progress_at TEXT
  CHECK(last_progress_at IS NULL OR julianday(last_progress_at) IS NOT NULL);
ALTER TABLE task_attempt ADD COLUMN progress_sequence INTEGER NOT NULL DEFAULT 0
  CHECK(progress_sequence>=0);

ALTER TABLE worker_lease ADD COLUMN resource_policy_version TEXT NOT NULL DEFAULT '1.0.0'
  CHECK(length(resource_policy_version) BETWEEN 1 AND 128);
ALTER TABLE worker_lease ADD COLUMN resource_class TEXT NOT NULL DEFAULT 'UNKNOWN'
  CHECK(length(resource_class) BETWEEN 1 AND 128);
ALTER TABLE worker_lease ADD COLUMN resource_preset TEXT NOT NULL DEFAULT 'CONSERVATIVE'
  CHECK(resource_preset IN ('CONSERVATIVE','STANDARD','HIGH','CUSTOM'));
ALTER TABLE worker_lease ADD COLUMN wall_clock_seconds INTEGER NOT NULL DEFAULT 3600
  CHECK(wall_clock_seconds>0);
ALTER TABLE worker_lease ADD COLUMN heartbeat_interval_seconds INTEGER NOT NULL DEFAULT 5
  CHECK(heartbeat_interval_seconds>0);
ALTER TABLE worker_lease ADD COLUMN lease_expiry_seconds INTEGER
  CHECK(lease_expiry_seconds IS NULL OR lease_expiry_seconds>=heartbeat_interval_seconds);
ALTER TABLE worker_lease ADD COLUMN host_snapshot_hash TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000'
  CHECK(
    length(host_snapshot_hash)=64
    AND host_snapshot_hash=lower(host_snapshot_hash)
    AND host_snapshot_hash NOT GLOB '*[^0-9a-f]*'
  );
ALTER TABLE worker_lease ADD COLUMN resolved_resource_json TEXT NOT NULL DEFAULT '{}'
  CHECK(json_valid(resolved_resource_json) AND length(CAST(resolved_resource_json AS BLOB))<=65536);
ALTER TABLE worker_lease ADD COLUMN resolved_resource_hash TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000'
  CHECK(
    length(resolved_resource_hash)=64
    AND resolved_resource_hash=lower(resolved_resource_hash)
    AND resolved_resource_hash NOT GLOB '*[^0-9a-f]*'
  );
ALTER TABLE worker_lease ADD COLUMN job_cpu_rate_per_10000 INTEGER
  CHECK(job_cpu_rate_per_10000 IS NULL OR job_cpu_rate_per_10000 BETWEEN 1 AND 10000);
ALTER TABLE worker_lease ADD COLUMN runtime_generation_id TEXT
  REFERENCES runtime_generation(runtime_generation_id);
ALTER TABLE worker_lease ADD COLUMN process_identity_hash TEXT
  CHECK(
    process_identity_hash IS NULL OR (
      length(process_identity_hash)=64
      AND process_identity_hash=lower(process_identity_hash)
      AND process_identity_hash NOT GLOB '*[^0-9a-f]*'
    )
  );
ALTER TABLE worker_lease ADD COLUMN scratch_root TEXT
  CHECK(scratch_root IS NULL OR length(scratch_root) BETWEEN 1 AND 4096);
ALTER TABLE worker_lease ADD COLUMN job_object_identity TEXT
  CHECK(job_object_identity IS NULL OR length(job_object_identity) BETWEEN 1 AND 256);
ALTER TABLE worker_lease ADD COLUMN enforcement_state TEXT NOT NULL DEFAULT 'NOT_CONFIGURED'
  CHECK(enforcement_state IN ('PENDING','VERIFIED','FAILED','NOT_CONFIGURED'));
ALTER TABLE worker_lease ADD COLUMN last_heartbeat_sequence INTEGER NOT NULL DEFAULT 0
  CHECK(last_heartbeat_sequence>=0);
ALTER TABLE worker_lease ADD COLUMN last_heartbeat_at TEXT
  CHECK(last_heartbeat_at IS NULL OR julianday(last_heartbeat_at) IS NOT NULL);
ALTER TABLE worker_lease ADD COLUMN worker_rss_bytes INTEGER NOT NULL DEFAULT 0
  CHECK(worker_rss_bytes>=0);
ALTER TABLE worker_lease ADD COLUMN worker_scratch_bytes INTEGER NOT NULL DEFAULT 0
  CHECK(worker_scratch_bytes>=0);
ALTER TABLE worker_lease ADD COLUMN parent_sample_memory_bytes INTEGER
  CHECK(parent_sample_memory_bytes IS NULL OR parent_sample_memory_bytes>=0);
ALTER TABLE worker_lease ADD COLUMN parent_sample_scratch_bytes INTEGER
  CHECK(parent_sample_scratch_bytes IS NULL OR parent_sample_scratch_bytes>=0);
ALTER TABLE worker_lease ADD COLUMN parent_sample_at TEXT
  CHECK(parent_sample_at IS NULL OR julianday(parent_sample_at) IS NOT NULL);

CREATE TABLE attempt_progress (
  attempt_id TEXT NOT NULL REFERENCES task_attempt(attempt_id),
  sequence INTEGER NOT NULL CHECK(sequence>=1),
  phase TEXT NOT NULL CHECK(phase IN (
    'DISPATCHED','EXECUTING','PUBLISHED',
    'ACQUIRING','VALIDATING','COMPUTING','PUBLISHING','RECONCILING'
  )),
  completed_units INTEGER NOT NULL CHECK(completed_units>=0),
  total_units INTEGER NOT NULL CHECK(total_units>=1),
  work_unit TEXT NOT NULL CHECK(length(work_unit) BETWEEN 1 AND 128),
  counters_json TEXT NOT NULL CHECK(
    json_valid(counters_json) AND length(CAST(counters_json AS BLOB))<=32768
  ),
  occurred_at TEXT NOT NULL,
  persisted_at TEXT NOT NULL,
  PRIMARY KEY(attempt_id,sequence),
  CHECK(completed_units<=total_units)
);

CREATE TABLE task_dispatch_control (
  task_id TEXT PRIMARY KEY REFERENCES task(task_id),
  state TEXT NOT NULL CHECK(state IN ('HOLD','READY','DISPATCHED','TERMINAL')),
  hold_reason TEXT CHECK(hold_reason IS NULL OR length(hold_reason) BETWEEN 1 AND 256),
  user_confirmed_at TEXT CHECK(user_confirmed_at IS NULL OR julianday(user_confirmed_at) IS NOT NULL),
  state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version>=0),
  updated_at TEXT NOT NULL
);

-- Existing catalogs have Tasks but no PR03 control rows.  Admission of a
-- migrated catalog must not leave those Tasks without a queue owner: terminal
-- Tasks are closed, while every non-terminal Task starts in an explicit HOLD
-- and requires a new user-confirmed READY -> DISPATCHED transition.
INSERT INTO task_dispatch_control(
  task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
)
SELECT task_id,
       CASE WHEN state IN ('SUCCEEDED','FAILED','CANCELLED','PARTIAL')
            THEN 'TERMINAL' ELSE 'HOLD' END,
       CASE WHEN state IN ('SUCCEEDED','FAILED','CANCELLED','PARTIAL')
            THEN NULL ELSE 'MIGRATION_RECONCILIATION' END,
       NULL,
       0,
       updated_at
FROM task;

CREATE TABLE control_operation_receipt (
  operation_receipt_id TEXT PRIMARY KEY CHECK(length(operation_receipt_id) BETWEEN 4 AND 128),
  correlation_id TEXT NOT NULL CHECK(length(correlation_id) BETWEEN 1 AND 256),
  operation_id TEXT NOT NULL CHECK(length(operation_id) BETWEEN 1 AND 256),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  task_id TEXT REFERENCES task(task_id),
  run_id TEXT REFERENCES run(run_id),
  attempt_id TEXT REFERENCES task_attempt(attempt_id),
  deadline_at TEXT NOT NULL CHECK(julianday(deadline_at) IS NOT NULL),
  runtime_generation_id TEXT REFERENCES runtime_generation(runtime_generation_id),
  state TEXT NOT NULL CHECK(state IN ('ACCEPTED','RUNNING','PRE_COMMIT_ABORTED','COMMITTED','SUCCEEDED','FAILED')),
  commit_boundary_at TEXT CHECK(commit_boundary_at IS NULL OR julianday(commit_boundary_at) IS NOT NULL),
  outcome_json TEXT CHECK(
    outcome_json IS NULL OR (
      json_valid(outcome_json) AND length(CAST(outcome_json AS BLOB))<=65536
    )
  ),
  outcome_artifact_id TEXT REFERENCES artifact(artifact_id),
  error_code TEXT CHECK(error_code IS NULL OR length(error_code) BETWEEN 1 AND 128),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  terminal_at TEXT CHECK(terminal_at IS NULL OR julianday(terminal_at) IS NOT NULL),
  state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version>=0),
  UNIQUE(correlation_id),
  CHECK(outcome_json IS NULL OR outcome_artifact_id IS NULL),
  CHECK(state NOT IN ('COMMITTED','SUCCEEDED') OR commit_boundary_at IS NOT NULL),
  CHECK(state NOT IN ('SUCCEEDED','FAILED') OR terminal_at IS NOT NULL),
  CHECK(state<>'FAILED' OR error_code IS NOT NULL)
);

CREATE INDEX idx_attempt_progress_latest
ON attempt_progress(attempt_id,sequence DESC);

CREATE INDEX idx_checkpoint_artifact_latest
ON checkpoint(artifact_id,created_at DESC,checkpoint_id DESC);

CREATE INDEX idx_task_dispatch_ready
ON task_dispatch_control(state,updated_at,task_id);

CREATE INDEX idx_runtime_generation_state
ON runtime_generation(clean_shutdown_at,started_at,runtime_generation_id);

CREATE INDEX idx_control_receipt_task_state
ON control_operation_receipt(task_id,state,updated_at,operation_receipt_id);

CREATE INDEX idx_control_receipt_project_state
ON control_operation_receipt(project_id,state,updated_at,operation_receipt_id);

CREATE INDEX idx_control_receipt_attempt
ON control_operation_receipt(attempt_id,created_at DESC,operation_receipt_id DESC);
