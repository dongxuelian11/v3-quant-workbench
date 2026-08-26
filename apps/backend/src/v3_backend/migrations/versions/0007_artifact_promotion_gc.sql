-- PR02: crash-reconcilable generic Artifact publication and two-phase GC.

CREATE TABLE artifact_promotion_intent (
  promotion_intent_id TEXT PRIMARY KEY CHECK(
    length(promotion_intent_id)=30 AND promotion_intent_id GLOB 'api_*'
  ),
  artifact_id TEXT NOT NULL CHECK(
    length(artifact_id)=75 AND artifact_id GLOB 'art_sha256_*'
  ),
  expected_sha256 TEXT NOT NULL CHECK(
    length(expected_sha256)=64
    AND expected_sha256=lower(expected_sha256)
    AND expected_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  expected_byte_size INTEGER NOT NULL CHECK(expected_byte_size>=0),
  staging_token TEXT NOT NULL UNIQUE CHECK(length(staging_token) BETWEEN 32 AND 128),
  staging_key TEXT NOT NULL,
  final_storage_key TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN(
    'STAGED_SYNCED','FINAL_PRESENT','CATALOG_COMMITTED',
    'CLEANUP_PENDING','FINALIZED','FAILED'
  )),
  state_version INTEGER NOT NULL CHECK(state_version>=1),
  descriptor_json TEXT NOT NULL CHECK(
    json_valid(descriptor_json) AND length(CAST(descriptor_json AS BLOB))<=65536
  ),
  references_json TEXT NOT NULL CHECK(
    json_valid(references_json) AND length(CAST(references_json AS BLOB))<=65536
  ),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT,
  last_error_code TEXT CHECK(last_error_code IS NULL OR length(last_error_code) BETWEEN 1 AND 128),
  last_error_detail_artifact_id TEXT
);

CREATE TABLE artifact_storage_error (
  storage_error_id TEXT PRIMARY KEY CHECK(
    length(storage_error_id)=30 AND storage_error_id GLOB 'ase_*'
  ),
  promotion_intent_id TEXT REFERENCES artifact_promotion_intent(promotion_intent_id),
  artifact_id TEXT CHECK(
    artifact_id IS NULL OR (
      length(artifact_id)=75 AND artifact_id GLOB 'art_sha256_*'
    )
  ),
  phase TEXT NOT NULL CHECK(phase IN(
    'STAGE_VERIFY','PROMOTION','CATALOG','CLEANUP','RECONCILIATION',
    'QUARANTINE','PURGE'
  )),
  error_code TEXT NOT NULL CHECK(length(error_code) BETWEEN 1 AND 128),
  observed_state_json TEXT NOT NULL CHECK(
    json_valid(observed_state_json) AND length(CAST(observed_state_json AS BLOB))<=65536
  ),
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE artifact_gc_batch (
  gc_batch_id TEXT PRIMARY KEY CHECK(
    length(gc_batch_id)=30 AND gc_batch_id GLOB 'gcb_*'
  ),
  phase TEXT NOT NULL CHECK(phase IN('QUARANTINE','PURGE')),
  scope_owner_id TEXT NOT NULL,
  plan_artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  reachability_fingerprint TEXT NOT NULL CHECK(
    length(reachability_fingerprint)=64
    AND reachability_fingerprint=lower(reachability_fingerprint)
    AND reachability_fingerprint NOT GLOB '*[^0-9a-f]*'
  ),
  exact_artifact_ids_hash TEXT NOT NULL CHECK(
    length(exact_artifact_ids_hash)=64
    AND exact_artifact_ids_hash=lower(exact_artifact_ids_hash)
    AND exact_artifact_ids_hash NOT GLOB '*[^0-9a-f]*'
  ),
  exact_artifact_ids_json TEXT NOT NULL CHECK(
    json_valid(exact_artifact_ids_json) AND length(CAST(exact_artifact_ids_json AS BLOB))<=65536
  ),
  open_intent_ids_json TEXT NOT NULL CHECK(
    json_valid(open_intent_ids_json) AND length(CAST(open_intent_ids_json AS BLOB))<=65536
  ),
  confirmation_nonce TEXT,
  confirmation_hash TEXT CHECK(
    confirmation_hash IS NULL OR (
      length(confirmation_hash)=64
      AND confirmation_hash=lower(confirmation_hash)
      AND confirmation_hash NOT GLOB '*[^0-9a-f]*'
    )
  ),
  state TEXT NOT NULL CHECK(state IN(
    'PLANNED','CONFIRMED','EXECUTING','COMPLETED','STALE','FAILED'
  )),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  confirmed_at TEXT,
  completed_at TEXT,
  UNIQUE(phase, plan_artifact_id, exact_artifact_ids_hash)
);

-- A plan request is claimed before its plan Artifact is published.  The
-- existing idempotency_record is append-only and is intentionally written
-- after a product response side effect; this small mutable record closes the
-- response-loss window without changing that table's contract.
CREATE TABLE artifact_gc_request (
  request_scope_key TEXT PRIMARY KEY CHECK(length(request_scope_key) BETWEEN 1 AND 1024),
  operation_id TEXT NOT NULL CHECK(operation_id IN(
    'ArtifactService.v1.planGarbageCollection',
    'ArtifactService.v1.planGarbagePurge'
  )),
  scope_owner_id TEXT NOT NULL REFERENCES project(project_id),
  canonical_request_hash TEXT NOT NULL CHECK(
    length(canonical_request_hash)=64
    AND canonical_request_hash=lower(canonical_request_hash)
    AND canonical_request_hash NOT GLOB '*[^0-9a-f]*'
  ),
  phase TEXT NOT NULL CHECK(phase IN('QUARANTINE','PURGE')),
  plan_json TEXT NOT NULL CHECK(
    json_valid(plan_json) AND length(CAST(plan_json AS BLOB))<=65536
  ),
  reachable_artifact_count INTEGER NOT NULL CHECK(reachable_artifact_count>=0),
  plan_artifact_id TEXT REFERENCES artifact(artifact_id),
  gc_batch_id TEXT REFERENCES artifact_gc_batch(gc_batch_id),
  state TEXT NOT NULL CHECK(state IN('IN_PROGRESS','COMPLETED')),
  outcome_json TEXT CHECK(
    outcome_json IS NULL OR (
      json_valid(outcome_json) AND length(CAST(outcome_json AS BLOB))<=65536
    )
  ),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(
    state='IN_PROGRESS'
    OR (plan_artifact_id IS NOT NULL AND gc_batch_id IS NOT NULL AND outcome_json IS NOT NULL)
  )
);

CREATE TABLE artifact_quarantine (
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  gc_batch_id TEXT NOT NULL REFERENCES artifact_gc_batch(gc_batch_id),
  quarantine_storage_key TEXT NOT NULL UNIQUE,
  original_storage_key TEXT NOT NULL,
  quarantined_at TEXT NOT NULL,
  purge_not_before TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN('MOVING','QUARANTINED','RESTORED','PURGED')),
  PRIMARY KEY(artifact_id, gc_batch_id)
);

CREATE TABLE artifact_gc_receipt (
  receipt_id TEXT PRIMARY KEY CHECK(
    length(receipt_id)=30 AND receipt_id GLOB 'agr_*'
  ),
  gc_batch_id TEXT NOT NULL REFERENCES artifact_gc_batch(gc_batch_id),
  result TEXT NOT NULL CHECK(result IN('QUARANTINED','RESTORED','PURGED','PARTIAL','FAILED')),
  exact_artifact_ids_hash TEXT NOT NULL CHECK(
    length(exact_artifact_ids_hash)=64
    AND exact_artifact_ids_hash=lower(exact_artifact_ids_hash)
    AND exact_artifact_ids_hash NOT GLOB '*[^0-9a-f]*'
  ),
  exact_bytes INTEGER NOT NULL CHECK(exact_bytes>=0),
  reclaimed_bytes INTEGER NOT NULL CHECK(reclaimed_bytes>=0),
  created_at TEXT NOT NULL,
  details_json TEXT NOT NULL CHECK(
    json_valid(details_json) AND length(CAST(details_json AS BLOB))<=65536
  )
);

CREATE INDEX idx_artifact_promotion_state
ON artifact_promotion_intent(state, updated_at, promotion_intent_id);

CREATE INDEX idx_artifact_storage_error_unresolved
ON artifact_storage_error(resolved_at, created_at, storage_error_id);

CREATE INDEX idx_artifact_gc_batch_state
ON artifact_gc_batch(phase, state, expires_at, gc_batch_id);

CREATE INDEX idx_artifact_quarantine_retention
ON artifact_quarantine(state, purge_not_before, artifact_id);

CREATE INDEX idx_artifact_gc_receipt_batch
ON artifact_gc_receipt(gc_batch_id, created_at, receipt_id);

CREATE INDEX idx_artifact_gc_request_state
ON artifact_gc_request(state, updated_at, request_scope_key);

-- A confirmed GC batch becomes an execution barrier while its exact bytes are
-- moving.  The application performs the same checks in its writer transaction
-- for the admission race; these Catalog guards close the gap for every other
-- writer and keep a new ACTIVE reference or open promotion from appearing
-- between the byte move and the Artifact state transition.
CREATE TRIGGER artifact_reference_gc_execution_barrier_i
BEFORE INSERT ON artifact_reference
WHEN NEW.state='ACTIVE' AND EXISTS (
  SELECT 1
  FROM artifact_gc_batch AS batch
  JOIN artifact_quarantine AS quarantine
    ON quarantine.artifact_id=NEW.artifact_id
  WHERE batch.state='EXECUTING'
    AND (
      (batch.phase='QUARANTINE'
       AND quarantine.gc_batch_id=batch.gc_batch_id
       AND quarantine.state='MOVING')
      OR (batch.phase='PURGE'
          AND quarantine.state='QUARANTINED'
          AND EXISTS (
            SELECT 1 FROM json_each(batch.exact_artifact_ids_json)
            WHERE json_each.value=NEW.artifact_id
          ))
    )
)
BEGIN
  SELECT RAISE(ABORT,'Artifact is under GC execution');
END;

CREATE TRIGGER artifact_reference_gc_execution_barrier_u
BEFORE UPDATE OF artifact_id,state ON artifact_reference
WHEN NEW.state='ACTIVE' AND EXISTS (
  SELECT 1
  FROM artifact_gc_batch AS batch
  JOIN artifact_quarantine AS quarantine
    ON quarantine.artifact_id=NEW.artifact_id
  WHERE batch.state='EXECUTING'
    AND (
      (batch.phase='QUARANTINE'
       AND quarantine.gc_batch_id=batch.gc_batch_id
       AND quarantine.state='MOVING')
      OR (batch.phase='PURGE'
          AND quarantine.state='QUARANTINED'
          AND EXISTS (
            SELECT 1 FROM json_each(batch.exact_artifact_ids_json)
            WHERE json_each.value=NEW.artifact_id
          ))
    )
)
BEGIN
  SELECT RAISE(ABORT,'Artifact is under GC execution');
END;

CREATE TRIGGER artifact_promotion_intent_gc_execution_barrier_i
BEFORE INSERT ON artifact_promotion_intent
WHEN NEW.state IN ('STAGED_SYNCED','FINAL_PRESENT','CATALOG_COMMITTED','CLEANUP_PENDING')
 AND EXISTS (
  SELECT 1
  FROM artifact_gc_batch AS batch
  JOIN artifact_quarantine AS quarantine
    ON quarantine.artifact_id=NEW.artifact_id
  WHERE batch.state='EXECUTING'
    AND (
      (batch.phase='QUARANTINE'
       AND quarantine.gc_batch_id=batch.gc_batch_id
       AND quarantine.state='MOVING')
      OR (batch.phase='PURGE'
          AND quarantine.state='QUARANTINED'
          AND EXISTS (
            SELECT 1 FROM json_each(batch.exact_artifact_ids_json)
            WHERE json_each.value=NEW.artifact_id
          ))
    )
 )
BEGIN
  SELECT RAISE(ABORT,'Artifact is under GC execution');
END;

CREATE TRIGGER artifact_promotion_intent_gc_execution_barrier_u
BEFORE UPDATE OF artifact_id,state ON artifact_promotion_intent
WHEN NEW.state IN ('STAGED_SYNCED','FINAL_PRESENT','CATALOG_COMMITTED','CLEANUP_PENDING')
 AND EXISTS (
  SELECT 1
  FROM artifact_gc_batch AS batch
  JOIN artifact_quarantine AS quarantine
    ON quarantine.artifact_id=NEW.artifact_id
  WHERE batch.state='EXECUTING'
    AND (
      (batch.phase='QUARANTINE'
       AND quarantine.gc_batch_id=batch.gc_batch_id
       AND quarantine.state='MOVING')
      OR (batch.phase='PURGE'
          AND quarantine.state='QUARANTINED'
          AND EXISTS (
            SELECT 1 FROM json_each(batch.exact_artifact_ids_json)
            WHERE json_each.value=NEW.artifact_id
          ))
    )
 )
BEGIN
  SELECT RAISE(ABORT,'Artifact is under GC execution');
END;

-- Once a batch is EXECUTING, the byte operation and its Catalog identity must
-- observe the same plan fields.  State/completion columns remain writable by
-- the coordinator's terminal transition; the binding columns do not.
CREATE TRIGGER artifact_gc_execution_binding_guard_u
BEFORE UPDATE OF phase,scope_owner_id,plan_artifact_id,
  reachability_fingerprint,exact_artifact_ids_hash,exact_artifact_ids_json,
  open_intent_ids_json,confirmation_nonce,confirmation_hash,created_at,expires_at
ON artifact_gc_batch
WHEN OLD.state='EXECUTING'
BEGIN
  SELECT RAISE(ABORT,'GC batch binding is immutable during execution');
END;

CREATE TRIGGER artifact_gc_execution_metadata_guard_u
BEFORE UPDATE ON artifact
WHEN EXISTS (
  SELECT 1
  FROM artifact_gc_batch AS batch
  WHERE batch.state='EXECUTING'
    AND EXISTS (
      SELECT 1 FROM json_each(batch.exact_artifact_ids_json)
      WHERE json_each.value=OLD.artifact_id
    )
)
AND (
  NEW.artifact_id IS NOT OLD.artifact_id
  OR NEW.sha256 IS NOT OLD.sha256
  OR NEW.byte_size IS NOT OLD.byte_size
  OR NEW.media_type IS NOT OLD.media_type
  OR NEW.semantic_role IS NOT OLD.semantic_role
  OR NEW.storage_key IS NOT OLD.storage_key
  OR NEW.safe_format_id IS NOT OLD.safe_format_id
  OR NEW.schema_fingerprint IS NOT OLD.schema_fingerprint
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.published_at IS NOT OLD.published_at
)
BEGIN
  SELECT RAISE(ABORT,'Artifact metadata is immutable during GC execution');
END;

CREATE TRIGGER artifact_gc_execution_quarantine_metadata_guard_u
BEFORE UPDATE ON artifact_quarantine
WHEN EXISTS (
  SELECT 1
  FROM artifact_gc_batch AS batch
  WHERE batch.state='EXECUTING'
    AND (
      batch.gc_batch_id=OLD.gc_batch_id
      OR (
        batch.phase='PURGE'
        AND EXISTS (
          SELECT 1 FROM json_each(batch.exact_artifact_ids_json)
          WHERE json_each.value=OLD.artifact_id
        )
      )
    )
)
AND (
  NEW.artifact_id IS NOT OLD.artifact_id
  OR NEW.gc_batch_id IS NOT OLD.gc_batch_id
  OR NEW.quarantine_storage_key IS NOT OLD.quarantine_storage_key
  OR NEW.original_storage_key IS NOT OLD.original_storage_key
  OR NEW.quarantined_at IS NOT OLD.quarantined_at
  OR NEW.purge_not_before IS NOT OLD.purge_not_before
)
BEGIN
  SELECT RAISE(ABORT,'GC quarantine metadata is immutable during execution');
END;

CREATE TRIGGER artifact_gc_active_reference_guard_u
BEFORE UPDATE OF state ON artifact
WHEN NEW.state IN ('QUARANTINED','DELETED')
 AND EXISTS (
  SELECT 1 FROM artifact_reference
  WHERE artifact_id=NEW.artifact_id AND state='ACTIVE'
 )
BEGIN
  SELECT RAISE(ABORT,'reachable Artifact cannot leave PUBLISHED state');
END;
