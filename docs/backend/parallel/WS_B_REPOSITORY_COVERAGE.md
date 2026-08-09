# WS-B Repository Contract Coverage

The implementation is a persistence foundation over bounded row mappings. It does not own domain
algorithms or ASL behavior.

| Repository boundary | SQLite tables / specialized surface |
|---|---|
| Project | project, append-only project_context_revision, desktop_session; current/append revision |
| Connector | connector/version/capability/admission/credential tables; version, admission, capability, active credential lookup |
| Instrument | instrument/revision/alias tables; interval-overlap rejection and as-of alias resolution |
| Snapshot | snapshot/raw/partition/validation/taxonomy tables; candidate, validation, validated publication, upgrade listing |
| Universe / Factor / Dataset / Strategy / Model | explicit bounded table sets and immutable publish_version with provenance closure |
| Study / Trial | study/trial/checkpoint tables; idempotent batch reservation, state CAS, latest checkpoint |
| Portfolio / Risk | explicit bounded table sets and immutable publication |
| Optimization | constraint/problem/solution tables; OPTIMAL weights require independently passed residual validation |
| Backtest | experiment/run-spec tables; expand-once, child dependency binding, immutable RunSpec |
| Result | Result/components; VALID requires independently passed reconciliation and a published reconciliation Artifact |
| Task | Task/Run/Attempt/dependency/Event/idempotency; sealed Run inputs, sequence CAS and ordered replay |
| Artifact | staged declaration, verified publication, immutable reachability references, release/reachable set, guarded tombstone |
| Provenance | entity/edge record-once and bounded recursive ancestor walk |

Every write requires an active explicit Unit of Work. Mutable aggregates use optimistic
row_version/state_version; immutable tables and terminal/published states are protected by
migration triggers.
