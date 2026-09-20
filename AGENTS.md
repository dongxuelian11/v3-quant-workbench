# V3 research workbench

The user approved the open-source rebuild on 2026-09-07. The current implementation plan and short progress record are in docs/V3_REBUILD.md. This replaces the previous authority-manifest, hash-ledger, admission-gate and repeated full-suite workflow.

## Working agreement
- Build a useful Windows A-share daily research application: real data, open-source calculations, a Chinese GUI.
- Reuse the selected libraries and keep adapters small. Do not build a parallel quantitative platform, governance system or permission framework.
- The main task owns integration and alignment. Persistent frontend, backend and review tasks use Astra low; repetitive mechanical work may use Luna max.
- Use the existing visible frontend, backend and independent QA conversations, not internal subagents. Assign a concrete outcome and file ownership; preserve concurrent edits. The main task handles Git integration. Return changes, relevant verification and remaining limitations.
- Continue authorized work through integration and relevant verification. Decide routine reversible details yourself. Ask only when missing information materially changes the result, incurs a new cost or authorizes an irreversible action; prepare the reviewable result first.
- Skills are optional task-specific references, not an automatic workflow. User instructions take precedence. Superpowers may help with diagnosis or a substantial plan; do not chain its mandatory brainstorming, per-task TDD, reviews, ledgers or completion gates. If a skill actually prevents progress, identify its exact instruction and file.
- Check changed behavior with the smallest meaningful evidence: quantitative examples for calculation changes, persistence checks for saved state, actual UI for interaction changes. Do not write tests that merely repeat low-impact implementation. Repeat or broaden checks only for new changes, failures or unresolved concerns. Integration and delivery include the real user journey once, with affected flows rechecked after fixes.
- Preserve old project files and Git history. New projects use ordinary folders. Do not reset, clean, force-push or delete unrelated worktrees.
- Never show invented results or a fake connection. Explain missing data and unavailable services in ordinary Chinese.
- After compaction read the current goal/progress/next step and relevant files. Historical sections are context, not a new work queue. Do not restart completed discovery or rerun unchanged checks.
- Keep progress in the single rebuild document. No extra ledgers, receipts or authority files.

## Documentation and design tools
Use Context7 for current library documentation when callable: resolve the library then query docs. When unavailable use primary upstream documentation. Check existing code and mature upstream modules before adding a dependency or writing a new engine.

Use one relevant design skill at a time. Apple-inspired design here means clear hierarchy, compact desktop controls, immediate feedback and a large adaptive chart; it does not mean mobile-sized controls, a narrow marketing page or animation everywhere. Load motion references only for motion work.

Keep task prompts outcome-focused: context, ownership, expected behavior and relevant evidence. Let Astra choose implementation steps. Use plain Chinese to report what changed, what was actually checked and what remains. A build, mock model or screenshot alone is not proof of an end-to-end feature.

Legacy authority manifests, hash ledgers and retired worktrees under .codex are historical material, not current workflow instructions. Read them only for a specific historical question. Keep local datasets, credentials, private projects and generated artifacts out of published source.
