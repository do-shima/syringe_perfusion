---
name: syringe-perfusion-verification-release
description: Standardize syringe_perfusion tests, Windows/PyInstaller builds, versioning, CI, release candidates, manifests, checksums, packaging, and upgrade preservation. Use for test infrastructure, build scripts, package-version changes, deployment preparation, artifact audits, or GitHub Actions. Do not use for ordinary source changes that require neither build nor release verification.
---

# Verification and Release

Compose this with project-workflow and, where relevant, hardware-safety, UI/UX, and review-closeout.

## Required inputs

- Requested verification/build/release scope and target version, if any.
- Current `pyproject.toml`, app/build identity, PyInstaller specs, build scripts, CI, tests, and previous artifacts.

## Verification workflow

1. Inspect documented test and build commands before changing them.
2. Run focused tests, then the complete pytest suite.
3. Run `git diff --check` and static safety scans.
4. Verify tests and smokes cannot access real serial hardware.
5. Validate wrappers: CRLF, no caret continuation, one `a4ctl` command per line, `%ROOT%`/Active Config consistency, and no hard-coded numeric COM assignments or personal paths.
6. When applicable, build GUI and CLI, then run packaged non-hardware smokes.
7. Verify external Active Config, runtime state, validation data, reports, NIS logs, and unknown data survive build/upgrade workflows.

## Version policy

- Treat `pyproject.toml` as canonical unless the repository explicitly changes policy.
- Keep GUI, CLI, reports, build identity, manifests, artifact names, changelog, and release notes consistent.
- Change `control_compatibility_version` only for material UART, flow, direction, START/STOP, timing, or calibration-interpretation behavior.
- Do not stale physical calibration for documentation or presentation-only changes.
- Read [references/version-policy.md](references/version-policy.md) for any version or compatibility decision.

## Non-negotiable release guardrails

1. Read [references/windows-build-checklist.md](references/windows-build-checklist.md) before a Windows release build.
2. Commit verified source before running the strict release build.
3. Require a clean tree for strict artifacts; do not use a development dirty-build override.
4. Never overwrite or relabel earlier versioned artifacts.
5. Generate SHA-256 files and a deterministic manifest.
6. Validate ZIP membership, every listed checksum, top-level checksum, required layout, and forbidden content.
7. Follow [references/release-artifact-policy.md](references/release-artifact-policy.md).
8. Do not tag, push, publish, or create a GitHub Release unless explicitly instructed.

## Required artifact checks

Exclude runtime/validation data, local logs, backups, caches, virtual environments, personal paths, secrets, local COM defaults, and local commissioning/run evidence. Include only generic installation config and required docs/wrappers/locales. Preserve existing writable data on upgrade.

## Output contract

Use [templates/release-closeout.md](templates/release-closeout.md). Report exact commands and results, version/commit/build identity, artifact paths and checksums, manifest verification, packaged smokes, preservation checks, signing status, unsupported checks, Git status, and publication actions not taken.
