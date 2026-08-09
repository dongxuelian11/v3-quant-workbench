# ASL Wire and DTO Conventions

The 17 `*.contract.json` files are normative machine-readable contracts. Their request schemas are closed at the top level (`additionalProperties:false`); domain-spec objects named in field descriptions are versioned value objects owned by the corresponding domain and must also reject unknown fields in implementation. No object field is a free-form action payload: its semantic type is fixed by its operation and DTO name.

Common scalar rules: IDs use the Domain Object Registry; UUID fields are UUIDv7; timestamps are RFC 3339 UTC; session dates are `YYYY-MM-DD`; hashes are lowercase SHA-256; money is `{amount_decimal:string,currency:"CNY"}`; ratios/objectives are decimal strings where exact comparison matters; enums are uppercase wire values. JSON numbers must be finite. Canonical request hashing uses RFC 8785-style canonical JSON with these scalar normalizations.

Common `ArtifactRefV1` is `{artifact_id,role,media_type,byte_size,sha256,schema_fingerprint?,access?}`. Access is omitted for metadata-only responses and is `{mode:"STREAM_TICKET",ticket_id,expires_at}` when authorized. Any variable-length numeric/time-series/table/ledger/model bytes use ArtifactRef; inline arrays are limited to identifiers, capability codes or other bounded control lists.

Common paged response is `{items:[bounded summary],next_cursor?:string,total_estimate?:integer}` with keyset cursor opaque to clients and page limit <=200 (event replay <=1000). Read models are presentation-safe projections, never domain entities or SQL rows. Every read model starts with `{schema_version:"1.0.0",truth_state,truth_reason_codes:[],provenance_summary,capabilities}` and uses ArtifactRefs for large sections.

Commands that return read models (`kind:COMMAND`) are synchronous Catalog mutations. `ASYNC_COMMAND` returns only durable Task/Run acceptance and completes through Task events/read models. Query methods are side-effect free except access audit. Deadline cancellation at transport level never substitutes for TaskService cancellation.

Compatibility: clients must ignore only fields introduced as optional in a negotiated minor version; unknown fields sent by clients are rejected. Enum expansion requires a minor version and clients must render unknown server enum as `UNAVAILABLE`, not guess. Major mismatch fails handshake. Error envelope is specified in `08_ERROR_TRUTH_STATE_TAXONOMY.md`.
