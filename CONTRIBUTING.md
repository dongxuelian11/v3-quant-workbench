# Contributing

This repository is currently a local frontend recovery candidate and is not yet published.

Before proposing a change:

1. Install the declared dependencies with `npm install`.
2. Run `npm run validate`.
3. Keep formal backend behavior behind the typed contracts in `packages/contracts`; do not add a private UI backend or silently turn demo data into formal output.
4. Document material recovery differences in `docs/recovery/frontend-reconstruction-delta.md`.

Do not add private market data, runtime databases, model weights, user strategies, credentials, or result artifacts.

