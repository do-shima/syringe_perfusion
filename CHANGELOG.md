# Changelog

## [0.2.0-beta.1] - 2026-07-30

Hardware-validation release candidate.

### Added

- Shared Active Config across GUI, CLI, and NIS wrappers.
- Armed dual-pump flow control with quantized setpoints.
- Process-safe START/STOP coordination and cancellable scheduled starts.
- Fail-closed target snapshots and independent emergency STOP attempts.
- Commissioning, calibration, balance, preflight, dashboard, and run history.
- Traceable build identity, sanitized diagnostics, CI, versioned Windows artifacts, checksums, and upgrade-preservation tooling.

### Safety and validation status

- The A4 protocol has no verified hardware readback: **PROGRAMMED — NOT READ BACK**.
- `COMPLETED_ESTIMATED` means only that programmed duration elapsed for the same run.
- Live flow changes while running remain unsupported.
- Physical direction, STOP, flow, balance, NIS, and microscope workstation commissioning remain required.
- Release-candidate executables are unsigned.

## Legacy history

The historical V1–V3.2 labels described UI/application generations before semantic package versioning. `v3.2-windows-app` remains a historical tag.
