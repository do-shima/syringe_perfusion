# Version and compatibility policy

- Read the current package version from `pyproject.toml`; do not invent an independent constant.
- Derive the human prerelease representation consistently from the package version.
- Keep GUI, CLI `--version`, commissioning/report identity, diagnostics, build metadata, manifest, artifact names, changelog, and release notes aligned.
- Embed Git/build identity at build time; do not query Git or the network during frozen startup.
- Mark dirty development builds visibly and reject dirty strict release builds.
- Never rewrite or relabel historical versioned artifacts.
- Name future tags consistently but create them only when explicitly instructed.

## Control compatibility

Change `control_compatibility_version` only when behavior material to UART commands, flow calculations, pump direction, START/STOP, timing, or calibration interpretation changes. Do not change it for documentation, localization, responsive layout, styling, accessibility, or other presentation-only work.

Use compatibility—not the full Git commit alone—to determine whether physical calibration evidence is materially stale. Still bind new commissioning records to exact build identity for traceability.
