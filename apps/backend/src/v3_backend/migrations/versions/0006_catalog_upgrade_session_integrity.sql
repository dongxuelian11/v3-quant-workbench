CREATE TABLE catalog_upgrade_receipt (
  operation_id TEXT PRIMARY KEY CHECK(operation_id GLOB 'cup_*'),
  source_catalog_path_fingerprint TEXT NOT NULL CHECK(length(source_catalog_path_fingerprint)=64),
  source_catalog_sha256 TEXT NOT NULL CHECK(length(source_catalog_sha256)=64),
  source_schema_prefix_json TEXT NOT NULL CHECK(json_valid(source_schema_prefix_json)),
  target_schema_prefix_json TEXT NOT NULL CHECK(json_valid(target_schema_prefix_json)),
  backup_path_fingerprint TEXT CHECK(backup_path_fingerprint IS NULL OR length(backup_path_fingerprint)=64),
  backup_sha256 TEXT CHECK(backup_sha256 IS NULL OR length(backup_sha256)=64),
  staged_sha256_before_replace TEXT NOT NULL CHECK(length(staged_sha256_before_replace)=64),
  final_catalog_sha256 TEXT NOT NULL CHECK(length(final_catalog_sha256)=64),
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

CREATE TRIGGER desktop_session_project_binding_immutable_guard
BEFORE UPDATE OF project_id ON desktop_session
WHEN NEW.project_id<>OLD.project_id
BEGIN
  SELECT RAISE(ABORT, 'desktop_session project binding is immutable');
END;
