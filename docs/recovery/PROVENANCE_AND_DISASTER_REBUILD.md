# Provenance and disaster rebuild

V3 originated as a private personal quantitative research workbench. A catastrophic local workspace loss made the former working tree unavailable as source authority. The public-source line was therefore rebuilt from accepted contracts, recovery evidence, and independently verified local Git commits rather than by importing private datasets or opaque binaries.

The current source authority is Git:

- the frontend reconstruction was committed as a current development baseline, explicitly not a final UI freeze;
- the independently accepted Canonical Backend Foundation history was merged with a visible no-fast-forward merge;
- public documentation records which financial-domain capabilities remain absent;
- task packages, local agent/ledger state, build output, market data, runtime databases, model weights, private projects, and real result artifacts are excluded from source.

The recovery history explains lineage but does not prove formal financial correctness. Data Truth, Research, Model, Portfolio/Risk, Backtest, and Result implementations require future bounded work and independent acceptance.

To rebuild the current technical baseline from a clean clone, use the pinned Node/npm and Python versions, run `npm ci`, then run `npm run validate:public`. No private disk path, provider credential, or local cache is an authority input to that route.
