# Optional Environment Profile Boundaries

The Canonical Core runtime and optional capability environments are separate authorities.

## Core

- Runtime: CPython 3.14.7 x86-64, standard GIL build.
- Current dependency profile: Python standard library only.
- Owns contracts, provenance, catalog/repositories, artifact coordination, task/worker control, resource governance, and local transport.

## Optional profiles

Qlib, RQData, RQAlpha, GPU/model specializations, and future Data/Model stacks must each be admitted through an explicit Environment Profile that records:

- purpose and capability boundary;
- compatible Python implementation/minor/patch;
- exact locked dependencies and wheel/platform evidence;
- process isolation and transport contract;
- credential and network policy;
- artifact/SBOM/license inventory;
- lifecycle, upgrade, and rollback policy.

An optional profile may use a different Python minor when required. It must communicate with Core through typed contracts and artifacts; it may not import itself into Core, replace Core authority, or silently turn unavailable capability into formal output.

## PB0 status

No optional profile is installed or admitted. DuckDB and Parquet ports remain fail-closed/unavailable in the Foundation. Data Truth and all financial-domain implementations remain future work.
