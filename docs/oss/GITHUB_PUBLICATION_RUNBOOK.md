# GitHub publication runbook

This is a later-action checklist. PB0 does not execute these commands.

## Preconditions

- The owner has selected a project license and committed the canonical `LICENSE` text.
- `npm ci` and `npm run validate:public` pass from a clean clone.
- Dependency/license matrix, SBOM, advisory result, and security/private-data scans are current.
- `git status --short` is clean and `git remote -v` shows no unintended remote.

## Later authorized sequence

```text
# Create an empty public repository through the owner's authenticated GitHub workflow.
# Do not initialize it with conflicting files.

git remote add origin <OWNER_AUTHORIZED_GITHUB_URL>
git remote -v
git push -u origin main
```

After the first push:

1. Confirm the hosted `ci` workflow passes.
2. Enable branch protection for `main`, require pull requests and the `ci` status check, and restrict force pushes/deletion.
3. Configure security contact/Private Vulnerability Reporting if desired.
4. Review repository visibility, default branch, Actions permissions, and dependency-update settings.
5. Create no tag or release until the owner separately authorizes a versioned release and verifies release artifacts.

Rollback before any collaborator work: remove or correct the remote only with explicit owner authorization. Never force-push this baseline as a cleanup shortcut.
