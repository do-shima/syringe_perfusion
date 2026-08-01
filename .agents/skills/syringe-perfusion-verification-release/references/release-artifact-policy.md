# Release artifact policy

## Include

- GUI executable and internal dependencies.
- CLI executable in its documented subdirectory.
- Generic tracked `pumps.json`, `profiles.json`, `syringes.json`, and `recipes.json` defaults.
- NIS wrappers and their README.
- installation, commissioning, NIS, release, and operator documentation.
- embedded build identity and required localization/resources.

## Exclude

- `config/runtime/`, `config/validation/`, local reports, run history, protocol/NIS logs.
- backup JSON files, temporary files, caches, test output, development environments, source-control data.
- personal paths, user names, secrets, tokens, machine identifiers, and local numeric COM defaults.
- mutable external data copied from an installed system.

## Manifest and checksum

- Sort file entries deterministically.
- Record distributed relative path, byte size, and SHA-256 for every file.
- Record release/package version, clean source commit, build identity, expected layout, writable directories, dependencies, and test summary.
- Compare manifest to final directory and ZIP; fail on missing, extra forbidden, or mismatched files.
- Generate and independently verify the top-level ZIP SHA-256.

## Upgrade preservation

- Prefer installation into a new versioned application directory.
- Treat Active Config, runtime state, validation, reports, and NIS logs as external writable data.
- Never copy packaged defaults over existing external JSON.
- Preserve local wrapper customization where feasible and document manual comparison when replacement is necessary.
