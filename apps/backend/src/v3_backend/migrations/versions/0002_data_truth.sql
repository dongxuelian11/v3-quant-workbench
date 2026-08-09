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

CREATE TABLE provider_capability (
  provider_id TEXT NOT NULL REFERENCES provider_descriptor(provider_id),
  capability_code TEXT NOT NULL,
  frequency TEXT NOT NULL,
  supplies_available_time INTEGER NOT NULL CHECK(supplies_available_time IN (0,1)),
  supplies_revisions INTEGER NOT NULL CHECK(supplies_revisions IN (0,1)),
  declaration_hash TEXT NOT NULL CHECK(length(declaration_hash)=64),
  declared_at TEXT NOT NULL,
  PRIMARY KEY(provider_id,capability_code)
);

CREATE TABLE instrument_classification (
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  board TEXT NOT NULL,
  security_category TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  available_time TEXT NOT NULL,
  evidence_artifact_id TEXT NOT NULL,
  PRIMARY KEY(instrument_id,effective_from),
  CHECK(effective_to IS NULL OR effective_to>effective_from)
);

CREATE TABLE raw_capture_truth_descriptor (
  raw_capture_id TEXT PRIMARY KEY REFERENCES raw_capture(raw_capture_id),
  provider_id TEXT NOT NULL REFERENCES provider_descriptor(provider_id),
  source_metadata_json TEXT NOT NULL CHECK(length(source_metadata_json)<=65536),
  provider_available_time TEXT,
  strict_pit_capable INTEGER NOT NULL CHECK(strict_pit_capable IN (0,1)),
  CHECK(strict_pit_capable=0 OR provider_available_time IS NOT NULL)
);

CREATE INDEX idx_raw_capture_provider ON raw_capture_truth_descriptor(provider_id,provider_available_time);

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
  available_time TEXT,
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
  available_time TEXT,
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
  universe_version_id TEXT NOT NULL REFERENCES universe_version(universe_version_id),
  instrument_id TEXT NOT NULL REFERENCES instrument(instrument_id),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  available_time TEXT,
  revision_id TEXT NOT NULL,
  provenance_artifact_id TEXT NOT NULL,
  CHECK(effective_to IS NULL OR effective_to>effective_from),
  UNIQUE(universe_version_id,instrument_id,effective_from,revision_id)
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

CREATE TRIGGER trg_provider_capability_append_only_u
BEFORE UPDATE ON provider_capability
BEGIN
  SELECT RAISE(ABORT,'provider_capability is append-only');
END;

CREATE TRIGGER trg_provider_capability_append_only_d
BEFORE DELETE ON provider_capability
BEGIN
  SELECT RAISE(ABORT,'provider_capability is append-only');
END;

CREATE TRIGGER trg_instrument_classification_artifact_i
BEFORE INSERT ON instrument_classification
WHEN NOT EXISTS (SELECT 1 FROM artifact WHERE artifact_id=NEW.evidence_artifact_id AND state='PUBLISHED')
BEGIN
  SELECT RAISE(ABORT,'Instrument classification must target a PUBLISHED Artifact');
END;

CREATE TRIGGER trg_instrument_classification_append_only_u BEFORE UPDATE ON instrument_classification BEGIN SELECT RAISE(ABORT,'instrument_classification is append-only'); END;
CREATE TRIGGER trg_instrument_classification_append_only_d BEFORE DELETE ON instrument_classification BEGIN SELECT RAISE(ABORT,'instrument_classification is append-only'); END;
CREATE TRIGGER trg_raw_capture_truth_append_only_u BEFORE UPDATE ON raw_capture_truth_descriptor BEGIN SELECT RAISE(ABORT,'raw_capture_truth_descriptor is append-only'); END;
CREATE TRIGGER trg_raw_capture_truth_append_only_d BEFORE DELETE ON raw_capture_truth_descriptor BEGIN SELECT RAISE(ABORT,'raw_capture_truth_descriptor is append-only'); END;

CREATE TRIGGER trg_instrument_classification_no_overlap_i
BEFORE INSERT ON instrument_classification
WHEN EXISTS (
  SELECT 1 FROM instrument_classification AS existing
  WHERE existing.instrument_id=NEW.instrument_id
    AND (existing.effective_to IS NULL OR existing.effective_to>NEW.effective_from)
    AND (NEW.effective_to IS NULL OR existing.effective_from<NEW.effective_to)
)
BEGIN
  SELECT RAISE(ABORT,'Instrument classification interval overlap');
END;

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

CREATE TRIGGER trg_universe_membership_no_overlap_i
BEFORE INSERT ON universe_membership_interval
WHEN EXISTS (
  SELECT 1 FROM universe_membership_interval AS existing
  WHERE existing.universe_version_id=NEW.universe_version_id
    AND existing.instrument_id=NEW.instrument_id
    AND (existing.effective_to IS NULL OR existing.effective_to>NEW.effective_from)
    AND (NEW.effective_to IS NULL OR existing.effective_from<NEW.effective_to)
)
BEGIN
  SELECT RAISE(ABORT,'Universe membership interval overlap');
END;

CREATE TRIGGER trg_data_snapshot_publish_truth_i
BEFORE UPDATE OF state ON data_snapshot
WHEN NEW.state='PUBLISHED' AND (
  NOT EXISTS (SELECT 1 FROM snapshot_partition WHERE snapshot_id=NEW.snapshot_id)
  OR NOT EXISTS (SELECT 1 FROM snapshot_raw_capture WHERE snapshot_id=NEW.snapshot_id)
  OR NOT EXISTS (SELECT 1 FROM snapshot_calendar WHERE snapshot_id=NEW.snapshot_id)
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
      LEFT JOIN raw_capture_truth_descriptor AS truth ON truth.raw_capture_id=source.raw_capture_id
      WHERE source.snapshot_id=NEW.snapshot_id
        AND (truth.raw_capture_id IS NULL OR truth.strict_pit_capable=0)
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
