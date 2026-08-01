# Windows build checklist

## Before building

- Confirm Windows, supported Python, pytest, PyInstaller, and pyserial versions.
- Record branch, commit, status, diff, upstream, package/human version, future tag, and control compatibility.
- Confirm source is clean before a strict release build.
- Run complete pytest, `git diff --check`, locale/static checks, and wrapper byte validation.
- Confirm CI/DRY-RUN settings prevent real serial access.

## Normal one-folder build

- Run the documented `scripts\build_windows.bat` command.
- Confirm GUI and CLI executable layouts exist.
- Confirm locale/assets/build identity are bundled.
- Run GUI no-port startup and CLI `--version`, `config-path`, `preflight`, `validation-status`, `recent-runs`, and diagnostics smokes.
- Confirm external Active Config is used and not overwritten.

## Strict release build

- Build from the verified source commit and clean tree.
- Embed clean build identity without user name, personal path, machine serial, secrets, or tokens.
- Assemble a new versioned directory; never replace an earlier artifact.
- Include generic config, wrappers, required docs, GUI/CLI, and internal runtime dependencies.
- Exclude local writable/evidence data.
- Generate ZIP, SHA-256 files, release notes, and manifest.
- Extract/revalidate ZIP membership and checksums.

## Closeout

- Record exact artifact and checksum.
- Report unsigned status unless signing was actually performed.
- State packaged visual/CLI checks and unsupported OS-scaling or hardware checks precisely.
- Confirm Git remains clean; do not tag or publish unless instructed.
