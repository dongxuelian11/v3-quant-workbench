-- The v1 Catalog required raw_capture.available_time.  WS-F makes provider
-- availability explicitly nullable; receipt/ingestion time remains separate.
CREATE TABLE raw_capture_ws_f (
  raw_capture_id TEXT PRIMARY KEY CHECK(raw_capture_id GLOB 'raw_*'),
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  provider_dataset TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
  effective_range_start TEXT,
  effective_range_end TEXT,
  available_time TEXT CHECK(available_time IS NULL OR (instr(available_time,'T')=11 AND datetime(available_time) IS NOT NULL)),
  provider_revision_id TEXT,
  captured_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('CAPTURED','QUARANTINED','ACCEPTED')),
  UNIQUE(connector_version_id,request_fingerprint,content_hash)
);

INSERT INTO raw_capture_ws_f SELECT * FROM raw_capture;
DROP TABLE raw_capture;

CREATE TABLE raw_capture (
  raw_capture_id TEXT PRIMARY KEY CHECK(raw_capture_id GLOB 'raw_*'),
  connector_version_id TEXT NOT NULL REFERENCES connector_version(connector_version_id),
  provider_dataset TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=64),
  effective_range_start TEXT,
  effective_range_end TEXT,
  available_time TEXT CHECK(available_time IS NULL OR (instr(available_time,'T')=11 AND datetime(available_time) IS NOT NULL)),
  provider_revision_id TEXT,
  captured_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('CAPTURED','QUARANTINED','ACCEPTED')),
  UNIQUE(connector_version_id,request_fingerprint,content_hash)
);

INSERT INTO raw_capture SELECT * FROM raw_capture_ws_f;
DROP TABLE raw_capture_ws_f;

CREATE INDEX idx_raw_capture_range ON raw_capture(connector_version_id,provider_dataset,effective_range_start,effective_range_end);

CREATE TRIGGER trg_raw_capture_published_artifact_i
BEFORE INSERT ON raw_capture
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_raw_capture_published_artifact_u
BEFORE UPDATE ON raw_capture
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Artifact reference must target a PUBLISHED Artifact');
END;

CREATE TABLE provider_descriptor (
  provider_id TEXT PRIMARY KEY CHECK(provider_id GLOB 'pvd_*'),
  stable_name TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  source_authority TEXT NOT NULL,
  metadata_json TEXT NOT NULL CHECK(length(metadata_json)<=65536),
  descriptor_hash TEXT NOT NULL CHECK(length(descriptor_hash)=64),
  state TEXT NOT NULL CHECK(state IN ('REGISTERED','DISABLED')),
  created_at TEXT NOT NULL
);

-- Extension/evidence only. connector_capability remains the single authority.
CREATE TABLE connector_data_capability (
  connector_version_id TEXT NOT NULL,
  capability_code TEXT NOT NULL,
  provider_id TEXT NOT NULL REFERENCES provider_descriptor(provider_id),
  logical_dataset TEXT NOT NULL,
  frequency TEXT NOT NULL,
  revision_semantics TEXT NOT NULL CHECK(revision_semantics IN ('REVISION_AWARE','SOURCE_IMMUTABLE','UNKNOWN')),
  provenance_required INTEGER NOT NULL CHECK(provenance_required=1),
  policy_artifact_id TEXT NOT NULL,
  declared_at TEXT NOT NULL,
  PRIMARY KEY(connector_version_id,capability_code),
  FOREIGN KEY(connector_version_id,capability_code)
    REFERENCES connector_capability(connector_version_id,capability_code),
  UNIQUE(connector_version_id,logical_dataset)
);

CREATE TABLE raw_capture_truth_descriptor (
  raw_capture_id TEXT PRIMARY KEY REFERENCES raw_capture(raw_capture_id),
  provider_id TEXT NOT NULL REFERENCES provider_descriptor(provider_id),
  source_metadata_json TEXT NOT NULL CHECK(length(source_metadata_json)<=65536),
  provider_available_time TEXT CHECK(provider_available_time IS NULL OR (instr(provider_available_time,'T')=11 AND datetime(provider_available_time) IS NOT NULL)),
  provenance_complete INTEGER NOT NULL CHECK(provenance_complete IN (0,1))
);

CREATE INDEX idx_raw_capture_provider ON raw_capture_truth_descriptor(provider_id,provider_available_time);

CREATE TABLE snapshot_validation_profile (
  validation_profile_id TEXT PRIMARY KEY,
  admission_state TEXT NOT NULL CHECK(admission_state IN ('PRE_ALPHA','FORMAL_ADMITTED')),
  description TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE snapshot_validation_requirement (
  validation_profile_id TEXT NOT NULL REFERENCES snapshot_validation_profile(validation_profile_id),
  check_code TEXT NOT NULL,
  required_state TEXT NOT NULL CHECK(required_state='PASS'),
  severity TEXT NOT NULL CHECK(severity='BLOCKING'),
  PRIMARY KEY(validation_profile_id,check_code)
);

CREATE TABLE snapshot_validation_binding (
  snapshot_id TEXT PRIMARY KEY REFERENCES data_snapshot(snapshot_id),
  validation_profile_id TEXT NOT NULL REFERENCES snapshot_validation_profile(validation_profile_id),
  bound_at TEXT NOT NULL
);

CREATE TABLE trading_calendar_version (
  calendar_version_id TEXT PRIMARY KEY CHECK(calendar_version_id GLOB 'tcv_*'),
  market TEXT NOT NULL,
  timezone TEXT NOT NULL,
  source_artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  state TEXT NOT NULL CHECK(state='PUBLISHED'),
  published_at TEXT NOT NULL,
  UNIQUE(market,content_hash)
);

CREATE TABLE trading_session (
  trading_session_id TEXT PRIMARY KEY CHECK(trading_session_id GLOB 'trs_*'),
  calendar_version_id TEXT NOT NULL REFERENCES trading_calendar_version(calendar_version_id),
  session_date TEXT NOT NULL,
  is_trading_day INTEGER NOT NULL CHECK(is_trading_day IN (0,1)),
  session_ordinal INTEGER NOT NULL CHECK(session_ordinal>=0),
  open_time TEXT,
  close_time TEXT,
  available_time TEXT CHECK(available_time IS NULL OR (instr(available_time,'T')=11 AND datetime(available_time) IS NOT NULL)),
  evidence_artifact_id TEXT NOT NULL,
  UNIQUE(calendar_version_id,session_date),
  UNIQUE(calendar_version_id,session_ordinal),
  CHECK((is_trading_day=1 AND open_time IS NOT NULL AND close_time IS NOT NULL AND close_time>open_time)
     OR (is_trading_day=0 AND open_time IS NULL AND close_time IS NULL))
);

CREATE TABLE snapshot_raw_capture (
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  raw_capture_id TEXT NOT NULL REFERENCES raw_capture(raw_capture_id),
  logical_dataset TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  PRIMARY KEY(snapshot_id,raw_capture_id,logical_dataset)
);

CREATE TABLE snapshot_calendar (
  snapshot_id TEXT PRIMARY KEY REFERENCES data_snapshot(snapshot_id),
  calendar_version_id TEXT NOT NULL REFERENCES trading_calendar_version(calendar_version_id),
  linked_at TEXT NOT NULL
);

CREATE TABLE corporate_action (
  corporate_action_id TEXT PRIMARY KEY CHECK(corporate_action_id GLOB 'coa_*'),
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  action_type TEXT NOT NULL CHECK(action_type IN ('CASH_DIVIDEND','STOCK_DIVIDEND','SPLIT','RIGHTS','MERGER','DELISTING')),
  effective_time TEXT NOT NULL,
  available_time TEXT CHECK(available_time IS NULL OR (instr(available_time,'T')=11 AND datetime(available_time) IS NOT NULL)),
  revision_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  raw_capture_id TEXT NOT NULL REFERENCES raw_capture(raw_capture_id),
  ledger_artifact_id TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  UNIQUE(instrument_id,action_type,effective_time,revision_id,provider)
);

CREATE TABLE adjustment_factor_version (
  adjustment_factor_version_id TEXT PRIMARY KEY CHECK(adjustment_factor_version_id GLOB 'afv_*'),
  snapshot_id TEXT NOT NULL REFERENCES data_snapshot(snapshot_id),
  basis TEXT NOT NULL CHECK(basis IN ('FORWARD','BACKWARD')),
  manifest_artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  state TEXT NOT NULL CHECK(state='PUBLISHED'),
  published_at TEXT NOT NULL,
  UNIQUE(snapshot_id,basis,content_hash)
);

CREATE TABLE universe_membership_interval (
  membership_interval_id TEXT PRIMARY KEY CHECK(membership_interval_id GLOB 'umi_*'),
  membership_fact_id TEXT NOT NULL CHECK(membership_fact_id GLOB 'umf_*'),
  universe_version_id TEXT NOT NULL REFERENCES universe_version(universe_version_id),
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  available_time TEXT CHECK(available_time IS NULL OR (instr(available_time,'T')=11 AND datetime(available_time) IS NOT NULL)),
  revision_id TEXT NOT NULL,
  membership_state TEXT NOT NULL CHECK(membership_state IN ('INCLUDED','EXCLUDED')),
  provenance_artifact_id TEXT NOT NULL,
  CHECK(effective_to IS NULL OR effective_to>effective_from),
  UNIQUE(universe_version_id,membership_fact_id,revision_id)
);

CREATE INDEX idx_trading_session_order ON trading_session(calendar_version_id,session_ordinal);
CREATE INDEX idx_corporate_action_pit ON corporate_action(instrument_id,effective_time,available_time);
CREATE INDEX idx_universe_membership_pit ON universe_membership_interval(universe_version_id,effective_from,effective_to,available_time);

CREATE TRIGGER trg_provider_descriptor_append_only_u
BEFORE UPDATE ON provider_descriptor
BEGIN
  SELECT RAISE(ABORT,'provider_descriptor is append-only');
END;

CREATE TRIGGER trg_provider_descriptor_append_only_d
BEFORE DELETE ON provider_descriptor
BEGIN
  SELECT RAISE(ABORT,'provider_descriptor is append-only');
END;

CREATE TRIGGER trg_connector_data_capability_authority_i
BEFORE INSERT ON connector_data_capability
WHEN NOT EXISTS (
  SELECT 1 FROM connector_capability AS authority
  JOIN connector_version AS version
    ON version.connector_version_id=authority.connector_version_id
  WHERE authority.connector_version_id=NEW.connector_version_id
    AND authority.capability_code=NEW.capability_code
    AND version.state='ADMITTED'
)
BEGIN
  SELECT RAISE(ABORT,'Data capability extension requires exact admitted ConnectorVersion authority');
END;

CREATE TRIGGER trg_connector_data_capability_artifact_i
BEFORE INSERT ON connector_data_capability
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.policy_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Data capability policy must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_connector_data_capability_append_only_u
BEFORE UPDATE ON connector_data_capability
BEGIN
  SELECT RAISE(ABORT,'connector_data_capability is append-only');
END;

CREATE TRIGGER trg_connector_data_capability_append_only_d
BEFORE DELETE ON connector_data_capability
BEGIN
  SELECT RAISE(ABORT,'connector_data_capability is append-only');
END;

CREATE TRIGGER trg_raw_capture_truth_append_only_u BEFORE UPDATE ON raw_capture_truth_descriptor BEGIN SELECT RAISE(ABORT,'raw_capture_truth_descriptor is append-only'); END;
CREATE TRIGGER trg_raw_capture_truth_append_only_d BEFORE DELETE ON raw_capture_truth_descriptor BEGIN SELECT RAISE(ABORT,'raw_capture_truth_descriptor is append-only'); END;

CREATE TRIGGER trg_snapshot_validation_profile_append_only_u BEFORE UPDATE ON snapshot_validation_profile BEGIN SELECT RAISE(ABORT,'snapshot_validation_profile is append-only'); END;
CREATE TRIGGER trg_snapshot_validation_profile_append_only_d BEFORE DELETE ON snapshot_validation_profile BEGIN SELECT RAISE(ABORT,'snapshot_validation_profile is append-only'); END;
CREATE TRIGGER trg_snapshot_validation_requirement_append_only_u BEFORE UPDATE ON snapshot_validation_requirement BEGIN SELECT RAISE(ABORT,'snapshot_validation_requirement is append-only'); END;
CREATE TRIGGER trg_snapshot_validation_requirement_append_only_d BEFORE DELETE ON snapshot_validation_requirement BEGIN SELECT RAISE(ABORT,'snapshot_validation_requirement is append-only'); END;
CREATE TRIGGER trg_snapshot_validation_binding_append_only_u BEFORE UPDATE ON snapshot_validation_binding BEGIN SELECT RAISE(ABORT,'snapshot_validation_binding is append-only'); END;
CREATE TRIGGER trg_snapshot_validation_binding_append_only_d BEFORE DELETE ON snapshot_validation_binding BEGIN SELECT RAISE(ABORT,'snapshot_validation_binding is append-only'); END;

CREATE TRIGGER trg_trading_calendar_artifact_i
BEFORE INSERT ON trading_calendar_version
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.source_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Trading Calendar must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_trading_session_artifact_i
BEFORE INSERT ON trading_session
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Trading Session must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_snapshot_raw_capture_admitted_i
BEFORE INSERT ON snapshot_raw_capture
WHEN NOT EXISTS (SELECT 1 FROM raw_capture WHERE raw_capture_id=NEW.raw_capture_id AND state='ACCEPTED')
  OR EXISTS (SELECT 1 FROM data_snapshot WHERE snapshot_id=NEW.snapshot_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Snapshot source must be ACCEPTED and linked before publication');
END;

CREATE TRIGGER trg_snapshot_calendar_admitted_i
BEFORE INSERT ON snapshot_calendar
WHEN EXISTS (SELECT 1 FROM data_snapshot WHERE snapshot_id=NEW.snapshot_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Snapshot Calendar must be linked before publication');
END;

CREATE TRIGGER trg_corporate_action_artifact_i
BEFORE INSERT ON corporate_action
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.ledger_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Corporate Action must target a PUBLISHED ledger Artifact');
END;

CREATE TRIGGER trg_adjustment_factor_artifact_i
BEFORE INSERT ON adjustment_factor_version
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.manifest_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Adjustment Factor must target a PUBLISHED manifest Artifact');
END;

CREATE TRIGGER trg_universe_membership_artifact_i
BEFORE INSERT ON universe_membership_interval
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.provenance_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Universe membership must target a PUBLISHED provenance Artifact');
END;

CREATE TRIGGER trg_data_snapshot_validate_complete_i
BEFORE UPDATE OF state ON data_snapshot
WHEN NEW.state='VALIDATED' AND (
  NOT EXISTS (
    SELECT 1 FROM snapshot_validation_binding
    WHERE snapshot_id=NEW.snapshot_id
  )
  OR EXISTS (
    SELECT 1
    FROM snapshot_validation_binding AS binding
    JOIN snapshot_validation_requirement AS requirement
      ON requirement.validation_profile_id=binding.validation_profile_id
    LEFT JOIN snapshot_validation AS result
      ON result.snapshot_id=binding.snapshot_id
     AND result.validation_profile_id=binding.validation_profile_id
     AND result.check_code=requirement.check_code
    WHERE binding.snapshot_id=NEW.snapshot_id
      AND (result.snapshot_validation_id IS NULL OR result.state<>requirement.required_state)
  )
  OR EXISTS (
    SELECT 1 FROM snapshot_validation AS result
    JOIN snapshot_validation_binding AS binding
      ON binding.snapshot_id=result.snapshot_id
     AND binding.validation_profile_id=result.validation_profile_id
    WHERE result.snapshot_id=NEW.snapshot_id
      AND result.severity='BLOCKING' AND result.state='FAIL'
  )
)
BEGIN
  SELECT RAISE(ABORT,'Snapshot validation profile is incomplete');
END;

CREATE TRIGGER trg_data_snapshot_publish_truth_i
BEFORE UPDATE OF state ON data_snapshot
WHEN NEW.state='PUBLISHED' AND (
  NOT EXISTS (SELECT 1 FROM snapshot_partition WHERE snapshot_id=NEW.snapshot_id)
  OR NOT EXISTS (SELECT 1 FROM snapshot_raw_capture WHERE snapshot_id=NEW.snapshot_id)
  OR NOT EXISTS (SELECT 1 FROM snapshot_calendar WHERE snapshot_id=NEW.snapshot_id)
  OR NOT EXISTS (SELECT 1 FROM snapshot_validation_binding WHERE snapshot_id=NEW.snapshot_id)
  OR (NEW.truth_profile_id='STRICT_PIT' AND EXISTS (
      SELECT 1 FROM snapshot_partition WHERE snapshot_id=NEW.snapshot_id AND max_available_time IS NULL
  ))
  OR (NEW.truth_profile_id='STRICT_PIT' AND EXISTS (
      SELECT 1 FROM snapshot_calendar AS binding
      JOIN trading_session AS session ON session.calendar_version_id=binding.calendar_version_id
      WHERE binding.snapshot_id=NEW.snapshot_id AND session.available_time IS NULL
  ))
  OR (NEW.truth_profile_id='STRICT_PIT' AND EXISTS (
      SELECT 1 FROM snapshot_raw_capture AS source
      JOIN raw_capture AS capture ON capture.raw_capture_id=source.raw_capture_id
      LEFT JOIN raw_capture_truth_descriptor AS truth ON truth.raw_capture_id=source.raw_capture_id
      LEFT JOIN connector_version AS version
        ON version.connector_version_id=NEW.connector_version_id
      LEFT JOIN connector_capability AS authority
        ON authority.connector_version_id=NEW.connector_version_id
       AND authority.capability_code=source.logical_dataset
      LEFT JOIN connector_data_capability AS policy
        ON policy.connector_version_id=NEW.connector_version_id
       AND policy.capability_code=source.logical_dataset
      WHERE source.snapshot_id=NEW.snapshot_id
        AND (
          capture.connector_version_id<>NEW.connector_version_id
          OR version.state<>'ADMITTED'
          OR truth.raw_capture_id IS NULL
          OR truth.provider_available_time IS NULL
          OR truth.provenance_complete=0
          OR authority.connector_version_id IS NULL
          OR authority.declared_state<>'DECLARED'
          OR authority.admitted_truth_state<>'FORMAL'
          OR policy.connector_version_id IS NULL
          OR policy.provider_id<>truth.provider_id
          OR policy.logical_dataset<>source.logical_dataset
          OR policy.revision_semantics='UNKNOWN'
        )
  ))
)
BEGIN
  SELECT RAISE(ABORT,'Snapshot publication truth precondition failed');
END;

CREATE TRIGGER trg_project_context_snapshot_i
BEFORE INSERT ON project_context_revision
WHEN NEW.snapshot_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM data_snapshot WHERE snapshot_id=NEW.snapshot_id AND state='PUBLISHED'
)
BEGIN
  SELECT RAISE(ABORT,'ProjectContext must reference a PUBLISHED SnapshotVersion');
END;

CREATE TRIGGER trg_project_context_snapshot_universe_compatible_i
BEFORE INSERT ON project_context_revision
WHEN NEW.snapshot_id IS NOT NULL AND NEW.universe_version_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM universe_version
  WHERE universe_version_id=NEW.universe_version_id AND snapshot_id=NEW.snapshot_id AND state='PUBLISHED'
)
BEGIN
  SELECT RAISE(ABORT,'ProjectContext Snapshot and Universe pins are incompatible');
END;

CREATE TRIGGER trg_trading_calendar_append_only_u BEFORE UPDATE ON trading_calendar_version BEGIN SELECT RAISE(ABORT,'trading_calendar_version is append-only'); END;
CREATE TRIGGER trg_trading_calendar_append_only_d BEFORE DELETE ON trading_calendar_version BEGIN SELECT RAISE(ABORT,'trading_calendar_version is append-only'); END;
CREATE TRIGGER trg_trading_session_append_only_u BEFORE UPDATE ON trading_session BEGIN SELECT RAISE(ABORT,'trading_session is append-only'); END;
CREATE TRIGGER trg_trading_session_append_only_d BEFORE DELETE ON trading_session BEGIN SELECT RAISE(ABORT,'trading_session is append-only'); END;
CREATE TRIGGER trg_snapshot_raw_capture_append_only_u BEFORE UPDATE ON snapshot_raw_capture BEGIN SELECT RAISE(ABORT,'snapshot_raw_capture is append-only'); END;
CREATE TRIGGER trg_snapshot_raw_capture_append_only_d BEFORE DELETE ON snapshot_raw_capture BEGIN SELECT RAISE(ABORT,'snapshot_raw_capture is append-only'); END;
CREATE TRIGGER trg_snapshot_calendar_append_only_u BEFORE UPDATE ON snapshot_calendar BEGIN SELECT RAISE(ABORT,'snapshot_calendar is append-only'); END;
CREATE TRIGGER trg_snapshot_calendar_append_only_d BEFORE DELETE ON snapshot_calendar BEGIN SELECT RAISE(ABORT,'snapshot_calendar is append-only'); END;
CREATE TRIGGER trg_corporate_action_append_only_u BEFORE UPDATE ON corporate_action BEGIN SELECT RAISE(ABORT,'corporate_action is append-only'); END;
CREATE TRIGGER trg_corporate_action_append_only_d BEFORE DELETE ON corporate_action BEGIN SELECT RAISE(ABORT,'corporate_action is append-only'); END;
CREATE TRIGGER trg_adjustment_factor_append_only_u BEFORE UPDATE ON adjustment_factor_version BEGIN SELECT RAISE(ABORT,'adjustment_factor_version is append-only'); END;
CREATE TRIGGER trg_adjustment_factor_append_only_d BEFORE DELETE ON adjustment_factor_version BEGIN SELECT RAISE(ABORT,'adjustment_factor_version is append-only'); END;
CREATE TRIGGER trg_universe_membership_append_only_u BEFORE UPDATE ON universe_membership_interval BEGIN SELECT RAISE(ABORT,'universe_membership_interval is append-only'); END;
CREATE TRIGGER trg_universe_membership_append_only_d BEFORE DELETE ON universe_membership_interval BEGIN SELECT RAISE(ABORT,'universe_membership_interval is append-only'); END;
