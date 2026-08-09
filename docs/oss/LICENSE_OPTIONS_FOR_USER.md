# Project license options for the owner

No option is selected by PB0. Dependency licenses do not choose the project's license.

The current npm lock contains permissive licenses (MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, 0BSD and `MIT OR CC0-1.0`) plus DOMPurify's `MPL-2.0 OR Apache-2.0` dual license. The Python Foundation currently uses only the standard library. No current dependency requires the V3 project itself to adopt a copyleft license.

| Option | Practical effect for V3 | Compatibility observation |
|---|---|---|
| MIT | Short and permissive; downstream users may modify, redistribute, and use commercially while retaining copyright/license notice. No express patent grant. | Compatible with the observed current dependency set. |
| Apache-2.0 | Permissive with an express patent grant/termination framework and NOTICE obligations where applicable. Longer and more explicit than MIT. | Compatible with the observed current dependency set; aligns naturally with Apache-2.0 dependencies. |
| MPL-2.0 | Weak/file-level copyleft: modifications to MPL-covered files distributed in executable form must make corresponding source available, while larger works may combine other licenses. | Compatible in principle with the observed permissive/dual-licensed dependency set, but imposes more downstream source-disclosure procedure. |

Assets and future dependencies must be reviewed separately. Generated screenshots, fonts, icons, market data, model artifacts, provider SDKs, and future optional environments can introduce rights or redistribution constraints that are not present in the current source baseline.

Owner decision required: choose one license, add its canonical text as root `LICENSE`, update package metadata and README, then independently re-run the license/SBOM gates before public push.
