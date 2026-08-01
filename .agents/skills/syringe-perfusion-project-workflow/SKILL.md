---
name: syringe-perfusion-project-workflow
description: Control scoped development and maintenance in syringe_perfusion. Use for features, bug fixes, refactors, documentation changes, repository audits, or maintenance; compose it with specialized safety, UI, release, HIL, or closeout skills as the task requires. Do not use it alone for a fixed-build physical validation session.
---

# Project Workflow

Apply this workflow to every repository modification. Treat the user request as the scope boundary and compose other project skills for specialized work.

## Required inputs

- The requested objective, permitted changes, prohibitions, verification, and commit policy.
- The current repository state and applicable `AGENTS.md` instructions.
- Relevant implementation, tests, documentation, and version policy discovered from the checkout.

## Workflow

1. Audit the starting state before editing:
   - current branch;
   - latest commit hash and message;
   - `git status --short`;
   - `git diff --stat`;
   - upstream name and ahead/behind status;
   - relevant existing tests and documented commands;
   - authoritative version source, normally `pyproject.toml`.
2. Inspect requested areas and their callers before proposing a design. Identify the milestone, authoritative modules, persisted data, compatibility surfaces, and tests.
3. Preserve unrelated local work. Do not discard, overwrite, stage, or explain it as task output unless it blocks the task.
4. Make the smallest coherent change that completes the requested scope. Preserve backward compatibility unless the user explicitly authorizes a break.
5. Keep responsibilities separated:
   - presentation in GUI modules;
   - orchestration in the shared coordinator and operations services;
   - runtime state in state modules;
   - configuration resolution and persistence in config modules;
   - hardware commands in the established hardware layer.
6. Reuse authoritative business logic from GUI and CLI. Do not create parallel resolvers, state machines, safety gates, or hardware paths. Avoid circular imports.
7. Verify in proportion to risk, including focused tests before the complete suite. Use the verification/release skill for build, packaging, CI, or version work.
8. Review the full diff, run `git diff --check`, and stage only task-related files.
9. Commit only after successful implementation and required verification. Use a Conventional Commits message. Do not push, merge, rebase, tag, or publish unless explicitly instructed.

## Non-negotiable guardrails

- Do not silently broaden scope or introduce experimental functionality.
- Do not overwrite deployed external Active Config, runtime state, validation evidence, commissioning reports, logs, or unknown JSON keys.
- Do not infer authorization for real serial communication or physical validation.
- Preserve the current package version unless versioning is explicitly in scope.
- Stop and report when completion requires materially new authority or unavailable physical evidence.

## Verification

- Run focused tests for changed behavior and the complete documented suite.
- Confirm no test opened a real serial port.
- Run required static/build checks selected by the task and relevant composed skills.
- Confirm `git status --short` after committing and report any remaining entries exactly.

## Output contract

Report the starting and ending commits, architecture decisions, files changed, tests and builds actually run, unresolved issues, physical checks not performed, Git status, commit hash, and commit message. Never claim evidence that was not produced.

Use [references/task-template.md](references/task-template.md) when converting a broad request into a compact execution brief.
