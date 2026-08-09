# Dependency advisory scan

Retrieval time: 2026-08-09T21:25:28+08:00

Source: the official npm Registry advisory endpoint, queried by npm 11.13.0 against the committed `package-lock.json`.

Commands:

```text
npm audit --json
npm audit --omit=dev --json
```

Both queries completed successfully at the advisory API level. npm returned a non-zero process status because findings were present, not because retrieval failed.

## Result

| Severity | Count |
|---|---:|
| Critical | 0 |
| High | 0 |
| Moderate | 1 |
| Low | 1 |
| Total aggregate dependency entries | 2 |

The Moderate finding is DOMPurify 3.4.8, pulled transitively by the direct runtime dependency Monaco Editor 0.56.0. npm reports several DOMPurify advisories at Low/Moderate severity and aggregates Monaco Editor as a Low affected direct dependency. The currently reported automated fix is a downgrade of Monaco Editor to 0.53.0, which would be a behavior-changing dependency change and is not accepted without separate regression work.

Current V3 usage creates Monaco editors over deterministic local Demo strings and does not call DOMPurify configuration APIs such as `setConfig`, `CUSTOM_ELEMENT_HANDLING`, `RETURN_TRUSTED_TYPE`, or `IN_PLACE`. This limits current exposure but does not erase the advisory. Track an upstream Monaco/DOMPurify resolution and re-run the audit before publication and after any editor input becomes externally controlled.

PB0's mandatory blocker is an unresolved High or Critical vulnerability in a shipped mandatory dependency. This scan contains neither; it therefore passes that bounded gate with the Moderate/Low findings explicitly retained.
