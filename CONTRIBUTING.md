# Contributing

V3 is pre-alpha and its project license is still unselected. External contribution mechanics should be considered provisional until the owner authorizes publication and adds a license.

Before proposing a change:

1. Use Node.js 24, npm 11, and CPython 3.14.7.
2. Install the exact JavaScript dependency graph with `npm ci`.
3. Run `npm run validate:public`; run `npm run validate` as well when a desktop Electron session is available.
4. Keep Demo data visibly non-formal. Do not imply that Data Truth, financial Research/Model, Portfolio/Risk, Backtest, or Result authority exists before its dedicated implementation and admission work.
5. Preserve the single Canonical Backend Foundation ownership boundaries and add focused tests for changed behavior.
6. Update `docs/status/CURRENT_STATUS.md` when a capability boundary changes.

Never add credentials, private market/provider captures, runtime databases, Parquet datasets, private strategies/projects, model weights, crash dumps, or real result artifacts. Generated dependencies and build output must remain untracked.

By participating, follow `CODE_OF_CONDUCT.md` and report security-sensitive findings through the private channel described in `SECURITY.md`, not a public issue.
