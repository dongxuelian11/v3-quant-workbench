CREATE TABLE catalog_upgrade_receipt (
  operation_id TEXT PRIMARY KEY CHECK(
    length(operation_id)=36
    AND substr(operation_id,1,4)='cup_'
    AND substr(operation_id,5) NOT GLOB '*[^0-9a-f]*'
  ),
  source_catalog_path_fingerprint TEXT NOT NULL CHECK(
    length(source_catalog_path_fingerprint)=64
    AND source_catalog_path_fingerprint=lower(source_catalog_path_fingerprint)
    AND source_catalog_path_fingerprint NOT GLOB '*[^0-9a-f]*'
  ),
  source_catalog_sha256 TEXT NOT NULL CHECK(
    length(source_catalog_sha256)=64
    AND source_catalog_sha256=lower(source_catalog_sha256)
    AND source_catalog_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  source_schema_prefix_json TEXT NOT NULL CHECK(json_valid(source_schema_prefix_json)),
  target_schema_prefix_json TEXT NOT NULL CHECK(json_valid(target_schema_prefix_json)),
  backup_path_fingerprint TEXT CHECK(
    backup_path_fingerprint IS NULL
    OR (
      length(backup_path_fingerprint)=64
      AND backup_path_fingerprint=lower(backup_path_fingerprint)
      AND backup_path_fingerprint NOT GLOB '*[^0-9a-f]*'
    )
  ),
  backup_sha256 TEXT CHECK(
    backup_sha256 IS NULL
    OR (
      length(backup_sha256)=64
      AND backup_sha256=lower(backup_sha256)
      AND backup_sha256 NOT GLOB '*[^0-9a-f]*'
    )
  ),
  staged_sha256_before_replace TEXT NOT NULL CHECK(
    length(staged_sha256_before_replace)=64
    AND staged_sha256_before_replace=lower(staged_sha256_before_replace)
    AND staged_sha256_before_replace NOT GLOB '*[^0-9a-f]*'
  ),
  final_catalog_sha256 TEXT NOT NULL CHECK(
    length(final_catalog_sha256)=64
    AND final_catalog_sha256=lower(final_catalog_sha256)
    AND final_catalog_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  integrity_check TEXT NOT NULL CHECK(integrity_check='PASS'),
  foreign_key_check TEXT NOT NULL CHECK(foreign_key_check='PASS'),
  replacement_mode TEXT NOT NULL CHECK(replacement_mode='SAME_VOLUME_ATOMIC_REPLACE'),
  started_at TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  recovery_action TEXT NOT NULL CHECK(recovery_action IN ('NONE','RESTORED_BACKUP')),
  result TEXT NOT NULL CHECK(result IN ('UPGRADED','NO_CHANGE','REFUSED','ROLLED_BACK')),
  error_code TEXT CHECK(error_code IS NULL OR length(error_code) BETWEEN 1 AND 128),
  CHECK((result='NO_CHANGE' AND backup_sha256 IS NULL AND backup_path_fingerprint IS NULL)
     OR (result<>'NO_CHANGE' AND backup_sha256 IS NOT NULL AND backup_path_fingerprint IS NOT NULL))
);

DROP TRIGGER desktop_session_project_binding_immutable_guard;

ALTER TABLE desktop_session
  ADD COLUMN canonical_session_uuid TEXT
  CHECK(
    canonical_session_uuid IS NULL
    OR (
      length(canonical_session_uuid)=36
      AND length(replace(canonical_session_uuid,'-',''))=32
      AND canonical_session_uuid=lower(canonical_session_uuid)
      AND canonical_session_uuid NOT GLOB '*[^0-9a-f-]*'
      AND substr(canonical_session_uuid,9,1)='-'
      AND substr(canonical_session_uuid,14,1)='-'
      AND substr(canonical_session_uuid,19,1)='-'
      AND substr(canonical_session_uuid,24,1)='-'
    )
  );

CREATE UNIQUE INDEX desktop_session_canonical_uuid_unique
ON desktop_session(canonical_session_uuid)
WHERE canonical_session_uuid IS NOT NULL;

CREATE TRIGGER desktop_session_project_binding_immutable_guard
BEFORE UPDATE OF project_id ON desktop_session
WHEN NEW.project_id<>OLD.project_id
BEGIN
  SELECT RAISE(ABORT, 'desktop_session project binding is immutable');
END;
