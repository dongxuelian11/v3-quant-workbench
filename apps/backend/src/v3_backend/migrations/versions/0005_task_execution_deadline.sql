ALTER TABLE task ADD COLUMN execution_deadline_at TEXT;

ALTER TABLE task_attempt ADD COLUMN execution_deadline_at TEXT;

CREATE TABLE task_output (
  task_id TEXT NOT NULL REFERENCES task(task_id),
  output_role TEXT NOT NULL CHECK(length(output_role) BETWEEN 1 AND 128),
  ordinal INTEGER NOT NULL DEFAULT 0 CHECK(ordinal>=0),
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  created_at TEXT NOT NULL,
  PRIMARY KEY(task_id,output_role,ordinal),
  UNIQUE(task_id,output_role,artifact_id)
);

CREATE TABLE publication_intent (
  publication_intent_id TEXT PRIMARY KEY CHECK(publication_intent_id GLOB 'pub_*'),
  project_id TEXT NOT NULL REFERENCES project(project_id),
  task_id TEXT NOT NULL REFERENCES task(task_id),
  run_id TEXT NOT NULL REFERENCES run(run_id),
  attempt_id TEXT NOT NULL REFERENCES task_attempt(attempt_id),
  intent_kind TEXT NOT NULL CHECK(length(intent_kind) BETWEEN 1 AND 128),
  state TEXT NOT NULL CHECK(state IN ('STAGED','BYTES_PUBLISHED','CATALOG_COMMITTED','RECONCILING','FINALIZED','FAILED')),
  expected_outputs_json TEXT NOT NULL CHECK(json_valid(expected_outputs_json) AND length(expected_outputs_json)<=65536),
  staged_manifest_json TEXT CHECK(staged_manifest_json IS NULL OR (json_valid(staged_manifest_json) AND length(staged_manifest_json)<=65536)),
  last_error_code TEXT CHECK(last_error_code IS NULL OR length(last_error_code)<=128),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT,
  state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version>=0),
  UNIQUE(task_id,attempt_id,intent_kind),
  CHECK(state!='FINALIZED' OR finalized_at IS NOT NULL)
);

CREATE TRIGGER task_execution_deadline_insert_guard
BEFORE INSERT ON task
WHEN NEW.execution_deadline_at IS NOT NULL
 AND (substr(NEW.execution_deadline_at, -1) <> 'Z' OR julianday(NEW.execution_deadline_at) IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'task execution_deadline_at must be RFC3339 UTC or null');
END;

CREATE TRIGGER task_execution_deadline_update_guard
BEFORE UPDATE OF execution_deadline_at ON task
WHEN NEW.execution_deadline_at IS NOT NULL
 AND (substr(NEW.execution_deadline_at, -1) <> 'Z' OR julianday(NEW.execution_deadline_at) IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'task execution_deadline_at must be RFC3339 UTC or null');
END;

CREATE TRIGGER task_attempt_execution_deadline_insert_guard
BEFORE INSERT ON task_attempt
WHEN NEW.execution_deadline_at IS NOT NULL
 AND (substr(NEW.execution_deadline_at, -1) <> 'Z' OR julianday(NEW.execution_deadline_at) IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'task_attempt execution_deadline_at must be RFC3339 UTC or null');
END;

CREATE TRIGGER task_attempt_execution_deadline_update_guard
BEFORE UPDATE OF execution_deadline_at ON task_attempt
WHEN NEW.execution_deadline_at IS NOT NULL
 AND (substr(NEW.execution_deadline_at, -1) <> 'Z' OR julianday(NEW.execution_deadline_at) IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'task_attempt execution_deadline_at must be RFC3339 UTC or null');
END;

CREATE TRIGGER desktop_session_project_context_owner_insert_guard
BEFORE INSERT ON desktop_session
WHEN NOT EXISTS (
  SELECT 1 FROM project_context_revision
  WHERE project_context_revision_id=NEW.project_context_revision_id
    AND project_id=NEW.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'desktop_session project/context binding mismatch');
END;

CREATE TRIGGER desktop_session_project_context_owner_update_guard
BEFORE UPDATE OF project_id,project_context_revision_id ON desktop_session
WHEN NOT EXISTS (
  SELECT 1 FROM project_context_revision
  WHERE project_context_revision_id=NEW.project_context_revision_id
    AND project_id=NEW.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'desktop_session project/context binding mismatch');
END;

CREATE TRIGGER desktop_session_project_binding_immutable_guard
BEFORE UPDATE OF project_id,project_context_revision_id ON desktop_session
WHEN NEW.project_id<>OLD.project_id
  OR NEW.project_context_revision_id<>OLD.project_context_revision_id
BEGIN
  SELECT RAISE(ABORT, 'desktop_session project binding is immutable');
END;

CREATE INDEX idx_task_discovery_cursor
ON task(project_id,service_name,state,created_at DESC,task_id);

CREATE INDEX idx_project_discovery_cursor
ON project(state,project_id);

CREATE INDEX idx_runspec_reference_cursor
ON artifact_reference(owner_id,role,state,artifact_id);

CREATE INDEX idx_task_output_artifact
ON task_output(artifact_id,task_id);

CREATE INDEX idx_publication_intent_recovery
ON publication_intent(state,updated_at,publication_intent_id);
