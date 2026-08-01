# Syringe Perfusion Codex Instructions

## Repository summary

This repository controls an A4 two-pump syringe-perfusion system through a Tkinter GUI, `a4ctl` CLI, NIS wrappers, shared Active Config, and process-safe runtime coordination. It also records commissioning, calibration, validation, diagnostics, and release evidence. Treat hardware movement and STOP behavior as safety-critical.

## Architecture summary

- Keep GUI modules as presentation and main-thread dispatch only.
- Reuse shared application services from GUI and CLI.
- Keep Active Config resolution/persistence in configuration modules.
- Keep run ownership, cancellation, target snapshots, and command-emission gates in the shared coordinator/state layer.
- Keep UART construction/emission in the established hardware layer.
- Keep commissioning, calibration, validation storage, preflight, and run-history responsibilities separated.

## Global rules

- Inspect before editing; preserve unrelated work and external user data.
- Never perform real serial communication unless the user explicitly authorizes a controlled physical session.
- Automated tests must not open a real serial port.
- Do not change UART, flow/quantization, coordinator, cancellation, STOP precedence, or scientific interpretation outside explicit scope.
- Do not duplicate business logic or safety state machines in GUI, CLI, recipes, legacy paths, or NIS.
- Run relevant focused tests and the complete documented suite; report only checks actually performed.
- Use Conventional Commits after successful requested implementation and verification.
- Do not push, merge, rebase, tag, or publish a release unless explicitly instructed.

## Skill index

Compose every relevant Skill; do not choose only one when scopes overlap.

- `syringe-perfusion-project-workflow` — use for every repository modification, maintenance task, documentation change, or implementation audit. Path: `.agents/skills/syringe-perfusion-project-workflow/SKILL.md`
- `syringe-perfusion-hardware-safety` — add whenever serial, pumps, ports, runtime state, scheduling, recipes, hardware CLI, NIS, START, cancellation, or STOP may be affected. Path: `.agents/skills/syringe-perfusion-hardware-safety/SKILL.md`
- `tkinter-laboratory-ui-ux` — add for GUI layout, responsive behavior, scrolling, localization, visual hierarchy, accessibility, keyboard behavior, or screenshot review. Path: `.agents/skills/tkinter-laboratory-ui-ux/SKILL.md`
- `syringe-perfusion-verification-release` — add for tests, CI, PyInstaller, Windows builds, versions, packaging, checksums, manifests, deployment, or release candidates. Path: `.agents/skills/syringe-perfusion-verification-release/SKILL.md`
- `syringe-perfusion-hil-commissioning` — use for fixed-build physical direction, STOP, flow, balance, NIS, and microscope-workstation validation. Path: `.agents/skills/syringe-perfusion-hil-commissioning/SKILL.md`
- `syringe-perfusion-review-closeout` — use for read-only audits, PR/milestone review, safety assessment, and final evidence classification. Path: `.agents/skills/syringe-perfusion-review-closeout/SKILL.md`

Example composition: a GUI change that affects START behavior requires project-workflow, tkinter-laboratory-ui-ux, hardware-safety, verification-release, and review-closeout.
