---
name: syringe-perfusion-review-closeout
description: Perform read-only audits and evidence-based milestone or validation closeout for syringe_perfusion. Use for post-implementation audits, pull-request review, safety review, HIL session disposition, milestone completion assessment, or deciding whether the next phase may begin. Do not implement fixes unless the user explicitly authorizes repair of identified defects.
---

# Review and Closeout

Begin read-only. Separate inspection evidence from implementation authorization. Compose hardware-safety when control paths are in scope and verification-release when builds/artifacts are assessed.

## Required inputs

- Milestone requirements or change description.
- Exact commit/worktree and, if applicable, artifact identity.
- Source, tests, documentation, logs, manifests, and reports required to verify claims.

## Review workflow

1. Record branch, commit, status, diff, upstream, and artifact identity.
2. Review repository architecture and responsibility boundaries.
3. Verify Active Config consistency across GUI, CLI, NIS, runtime state, and validation storage.
4. Verify GUI/CLI/NIS behavior uses authoritative shared services.
5. Review hardware safety invariants, threading, cancellation, target persistence, and stale state where relevant.
6. Review persistence, atomicity, unknown-field compatibility, and user-data preservation.
7. Map requirements to automated tests, packaged checks, manual visual checks, and physical evidence.
8. Review Windows build/release evidence when claimed.
9. Review documentation, public defaults, wrappers, path leakage, and numeric COM leakage.
10. List remaining physical validation explicitly.

## Finding severity

- **P0:** safety or correctness blocker; fix before new functionality or real operation.
- **P1:** should be fixed in the current or next milestone.
- **P2:** non-blocking debt that can wait.

## Completion classification

Choose exactly one using [references/completion-classification.md](references/completion-classification.md):

- COMPLETE
- COMPLETE WITH NON-BLOCKING DEBT
- INCOMPLETE
- BLOCKED
- SOFTWARE MILESTONE COMPLETE — HARDWARE VALIDATION INCOMPLETE

## Non-negotiable evidence rules

- Do not claim a test, build, visual check, or physical check that was not performed.
- Distinguish source inspection, automated tests, packaged smoke, manual visual review, and physical evidence.
- Do not infer hardware validation from mocks or UART completion.
- Identify exact commits and artifacts.
- Create no empty commit for a read-only audit.

## Output contract

Use [templates/audit-report.md](templates/audit-report.md) for detailed audits or [templates/final-report.md](templates/final-report.md) for implementation closeout. Provide concrete file locations, P0/P1/P2 findings, readiness/classification, remaining blockers, recommended order, verification evidence, Git state, and a concise TODO list.
