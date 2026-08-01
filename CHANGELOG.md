# Changelog

## [0.2.0-beta.4] - 2026-08-01

Superseding hardware-validation release candidate. Beta.3 remains historical but is superseded for routine HIL operation because the primary Experiment screen exposed too many independent settings simultaneously.

### Added

- Added a four-step guided workflow matching laboratory order: Experimental Conditions, Pump Setup, Microscope / NIS Preparation, and Run.
- Added persistent text-and-icon progress, prerequisite gating, a compact experiment summary, recent-condition and template shortcuts, and session-only NIS preparation checks.
- Added explicit immediate/delayed NIS wrapper guidance and copy/open/config-agreement actions that never move pumps.

### Changed

- Reduced normal top-level navigation to Experiment, History, and Management / Advanced while retaining hardware, commissioning, profile, calculator, Recipe, manual/jog, diagnostics, and compatibility functions.
- Moved quantization, exact UART commands, raw identifiers, complete paths, and technical logs behind progressive disclosure.
- Added responsive wide side-by-side and narrow stacked workflow layouts with fixed progress, primary action, summary, and STOP access.
- Changing scientific conditions, syringes, or ports now visibly invalidates later workflow readiness and explains that pump programming must be repeated.

### Compatibility

- Control compatibility remains `1`; UART, flow, quantization, timing, START/STOP coordination, cancellation, target snapshots, runtime state, preflight, commissioning, calibration, CLI, and NIS wrapper behavior are unchanged.

## [0.2.0-beta.3] - 2026-08-01

Superseding hardware-validation release candidate. Beta.2 remains historical but is superseded for HIL use because the Recipe editor and secondary workspaces were not sufficiently usable at normal and high-DPI window sizes.

### Fixed

- Replaced the vertically expensive Recipe step cards with a compact, scrollable Treeview and one shared movement toolbar.
- Added responsive wide three-pane and narrow stacked Recipe layouts plus an independently scrollable Inspector.
- Replaced white-on-white secondary buttons with visible neutral, outline, focus, pressed, disabled, success, warning, and danger treatments.
- Localized structured Profile and Calculator results, Setup source values, History states, and About / Diagnostics fields.
- Distinguished active faults from historical faults and added non-destructive acknowledgement of resolved historical warnings.
- Suppressed executable OUT values and changed PROGRAM / ARM wording when OUT is disabled.

### Added

- Unsaved Recipe tracking and protected New, Open, and close flows.
- Recipe keyboard shortcuts, compact/collapsible technical logs, responsive History scrollbars, and structured copyable build paths.
- Deterministic geometry, localization, visual-style, focus, fault, and OUT-disabled presentation tests.

### Compatibility

- Control compatibility remains `1`; UART, flow, quantization, timing, START/STOP, cancellation, snapshots, preflight, commissioning, calibration, CLI, and NIS behavior are unchanged.

## [0.2.0-beta.2] - 2026-07-30

Superseding hardware-validation release candidate. Beta.1 is retained as historical evidence but is superseded for HIL use because lower Experiment controls were inaccessible in the initial viewport.

### Fixed

- Rebuilt Experiment as a fixed header/action/footer layout with a vertically scrollable content viewport.
- Added deterministic narrow one-column and wide two-column layouts with responsive text wrapping.
- Removed conflicting `bind_all` / `unbind_all` mouse-wheel behavior from reusable scrolling workspaces.

### Added

- Complete UTF-8 English and Japanese GUI catalogs, Auto locale detection, persistent UI-only language choice, and runtime switching.
- Canonical display mappings that keep modes, states, JSON values, protocol bytes, run IDs, and scientific settings language-independent.
- Japanese-capable Windows font selection with safe fallbacks.

### Compatibility

- Control compatibility remains `1`; UART, flow, timing, START/STOP, cancellation, commissioning, and calibration interpretation are unchanged.

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
