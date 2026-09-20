# Contributing

V3 is a Windows A-share research desktop under the [Apache-2.0 license](LICENSE). Current scope and unfinished work are in [docs/V3_REBUILD.md](docs/V3_REBUILD.md); collaboration guidance is in [AGENTS.md](AGENTS.md).

Before proposing a change:

1. Use the versions in `.node-version` and `.python-version` (Python 3.12).
2. Install the exact JavaScript dependency graph with `npm ci`.
3. Verify the affected behavior: a focused example or test for calculations and persistence, and the actual interface for UI changes. Do not run the entire suite for every small edit.
4. `npm run build` includes TypeScript checks and builds the desktop. `npm test` runs the research suite for integration. CI builds pull requests; main integration or a manual run also checks research calculations. Installer builds remain manual.
5. Reuse existing research services and upstream libraries. Preserve concurrent changes and existing user projects; distinguish implemented behavior from actual end-to-end verification.
6. Keep progress in `docs/V3_REBUILD.md`, without extra status ledgers.

Never add credentials, private market/provider captures, runtime databases, Parquet datasets, private strategies/projects, model weights, crash dumps, or real result artifacts. Generated dependencies and build output must remain untracked.

When reporting an issue, include reproducible steps and the application version. Remove API keys and private research data from attachments.
