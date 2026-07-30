# A4 Syringe Pump Control

Version: V3.2  
GUI: Tkinter/ttk + clam theme + custom Style  
Control: USB-TTL UART  
Distribution: PyInstaller one-folder  
Dependencies: Python + pyserial for source run; no Python needed for built app

## Overview

A4/QHZS系シリンジポンプをUSB-TTL UART経由で制御する軽量Python/Windowsアプリです。GUI、CLI、Single Pump Mode、Manual Hold、Jog、速度・時間設定の書き込み、Recipe Builder、NIS-Elements連携、PyInstaller配布、アプリアイコン/アセット管理に対応しています。

研究室内の顕微鏡PCや実験用Windows PCで、追加GUI依存を増やさずに動かすことを前提にしています。

## Active Config（GUI / CLI / NIS共通）

GUI、CLI、NIS wrapperは、必ず1つのActive Config Directoryにある次の4ファイルを一組として読みます。

- `pumps.json`
- `profiles.json`
- `syringes.json`
- `recipes.json`

標準のWindows配布先は `<A4PUMP_ROOT>\config` です。GUIのSetup画面でCOM設定を保存すると、その外部 `pumps.json` をatomic置換し、バックアップ `pumps.json.bak` を作ります。CLIを再起動すれば同じJSONを読み、外部エディタで変更した内容はGUIの `Reload from JSON` で反映されます。`_internal\default_config` または旧 `_internal\config` は初期コピー元であり、直接編集しません。

`--config-dir` 省略時の共通探索順は次の通りです。

1. APIまたはCLIの明示 `--config-dir`
2. 環境変数 `A4PUMP_CONFIG_DIR`
3. GUIで選択し `%LOCALAPPDATA%\A4PumpControl\settings.json` に保存された場所
4. exe-adjacent `<A4PUMP_ROOT>\config`
5. `%LOCALAPPDATA%\A4PumpControl\config`
6. Source実行時のみリポジトリの `config`
7. packaged default（コピー元のみ。Active Configにはしない）

Frozen版は起動時のcurrent directoryを探索に使いません。診断:

```powershell
a4ctl.exe config-path
a4ctl.exe config-path --json
```

GUIで別のActive Configを選んだ場合、CLI省略時のresolverはその保存済み選択を使います。一方、NIS wrapperは再現性のため常に `--config-dir` を明示するので、Setup画面の `Copy NIS CFG line` でwrapperのCFGも同じ場所へ合わせてください。

## Armed perfusion flow control

Experiment is the primary operational screen. Its safe workflow is:

1. Scan ports and select independent IN and OUT devices.
2. Test IN and OUT by opening/closing each port; connection tests send no pump command.
3. Choose Fixed volume, Fixed duration, or Bounded continuous.
4. Set IN flow with the exact numeric entry or convenience slider.
5. Select IN/OUT syringes and review the quantized preview.
6. Switch from DRY-RUN to LIVE.
7. Select **PROGRAM / ARM BOTH**.
8. Confirm **PROGRAMMED — NOT READ BACK**.
9. Start acquisition and call an armed NIS wrapper.
10. Use GUI **STOP ALL**, Esc, or `pump_stop_all.cmd` to cancel/stop.

The numeric flow entry is authoritative. The 0.1–3.0 mL/min slider, ±0.1 buttons, and preset buttons update preview only; slider movement sends no UART commands and does not rewrite `profiles.json`. An exact value outside the visible slider range is retained when it is within device limits.

Calculation modes:

- **Fixed volume**: IN flow and target IN volume determine the common duration.
- **Fixed duration**: IN flow and duration determine expected volume.
- **Bounded continuous**: requires a maximum duration; unbounded operation is rejected.

IN is calculated for forward operation and OUT for reverse operation. OUT ratio lock defaults to 1.00. It can be changed to values such as 0.90/1.10, or disabled for independent OUT flow. Unequal flow can change dish volume. IN and OUT use their own syringe calibration and the same quantized duration.

Preview and programming reuse the verified A4 `ROUND_HALF_UP` resolution:

- speed: 0.01–150.00 mm/min, 0.01 mm/min increments
- duration: 1 second–99:59:59, whole seconds

The preview shows requested flow, programmed speed/duration, estimated actual flow/volume, quantization difference, and exact UART commands.

### Shared runtime state

Armed and pending state is shared by GUI, CLI, and NIS under the same Active Config:

```text
<ACTIVE_CONFIG>\runtime\perfusion_state.json
<ACTIVE_CONFIG>\runtime\pending_run.json
<ACTIVE_CONFIG>\runtime\run.lock
<ACTIVE_CONFIG>\runtime\protocol_runner.log
```

The runtime directory is created only when needed, is not a fifth required config file, is not packaged, and is preserved by rebuilds. Runtime JSON uses atomic UTF-8 writes.

State transitions include:

```text
DIRTY -> PROGRAMMING -> ARMED -> PENDING -> STARTING -> STARTED
STARTED -> COMPLETED_ESTIMATED
any active state -> STOPPING -> STOPPED
recipe/manual compatibility operation -> RECIPE_RUNNING -> COMPLETED_ESTIMATED
any operational state -> FAULT
```

PROGRAM / ARM first stops enabled pumps, programs/saves OUT, then programs/saves IN. `ARMED` is persisted only after both complete. The pump does not provide verified setting readback, so the UI deliberately says **PROGRAMMED — NOT READ BACK**. Any partial programming/start failure attempts STOP on both pumps and records `FAULT`.

Changing ports, serial settings, syringes, flow/mode, ratio, duration/volume, delay, relevant config, or Active Config invalidates the shared state to `DIRTY`. NIS therefore cannot start a stale GUI plan.

### Armed CLI commands

```powershell
a4ctl.exe --config-dir "<CFG>" arm-status
a4ctl.exe --config-dir "<CFG>" arm-status --json
a4ctl.exe --config-dir "<CFG>" start-armed --dish-id NIS --condition perfusion --trigger-source NIS
a4ctl.exe --config-dir "<CFG>" schedule-armed --delay-s 300 --dish-id NIS --condition perfusion_delayed --trigger-source NIS
a4ctl.exe --config-dir "<CFG>" cancel-pending
a4ctl.exe --config-dir "<CFG>" stop-all
```

`start-armed` is always immediate: it sends only the persisted IN-forward and OUT-reverse start commands and does not recalculate or rewrite settings. `schedule-armed --delay-s N` launches a detached worker and returns a run ID promptly. The GUI **GUI START delay sec** field uses this same scheduler when greater than zero; it does not change CLI `start-armed`.

Scheduled, IN-to-OUT, recipe, and jog waits use the shared persisted cancellation token. START authorization is rechecked at the UART write boundary. Once STOP is accepted by the command gate for a run, no later START command for that run is authorized. STOP uses persisted active/pending/armed target snapshots before editable `pumps.json`, attempts every unique target independently, and reports `STOP_FAILED` if any STOP fails.

`COMPLETED_ESTIMATED` is persisted only when the programmed duration has elapsed for the same still-`STARTED` run. It is an elapsed-time estimate and is not pump readback.

No speed is changed while RUNNING/STARTED. This milestone intentionally has no live-flow adjustment.

## Key Features

- USB-TTL UART control for A4 syringe pump
- Single pump mode with optional OUT pump
- Manual hold and bounded jog
- Write speed/time settings to A4
- Fast-30 profile
- Recipe Builder
- Dry-run
- CSV logging
- NIS-Elements 6.02 integration via `Int_ExecProgram`
- PyInstaller Windows app
- Icon and logo assets

## Current Validated Setup

- Windows
- NIS-Elements 6.02
- `a4ctl.exe` called from `.cmd` files
- `A4PumpGUI.exe` confirmed working
- `.cmd` wrappers confirmed from PowerShell and NIS macro
- A4 pump control confirmed from PowerShell and NIS macro
- PowerShell and NIS macro execution confirmed
- The actual COM port and installation directory depend on the microscope PC.
- Set the shared Active Config through GUI Setup; tracked `.cmd` wrappers do not contain COM settings.

In this document, `<A4PUMP_ROOT>` denotes the installation folder of the built application. For example, `C:\A4PumpKit`.

Recommended structure:

```text
<A4PUMP_ROOT>\
  A4PumpGUI.exe
  a4ctl\
    a4ctl.exe
  config\
    pumps.json
    profiles.json
    syringes.json
    recipes.json
  nis_cmd\
    00_check_paths.cmd
    pump_test_dryrun.cmd
    pump_start_armed.cmd
    pump_start_armed_after_300s.cmd
    pump_cancel_pending.cmd
    pump_write_in_out.cmd
    pump_start_pushpull_fast30.cmd
    pump_stop_all.cmd
  nis_logs\
  _internal\
```

The actual COM port depends on the Windows PC. Check it with `list-ports` and set `config/pumps.json` accordingly. For example, set `IN.port` to `COMx`, where `COMx` is the USB-TTL adapter port shown by Windows Device Manager or `a4ctl list-ports`.

## Hardware Connection

A4 controller connector:

```text
T R G V
```

Connection:

```text
A4 T -> USB-TTL RXD
A4 R -> USB-TTL TXD
A4 G -> USB-TTL GND
A4 V -> not connected
```

Important:

- A4 `V` must not be connected to 3.3 V or 5 V.
- A4本体は通常の12 V電源で動かします。
- USB-TTL変換器はCP2102N、CH340Gなどを使います。
- USB-RS232変換器やUSB D+/D-直結ケーブルは使いません。

## Communication Protocol

実機では小文字ASCIIコマンドで動作確認済みです。大文字コマンドではなく、小文字で送信してください。

- Baudrate: 9600
- Data format: 8N1
- Flow control: none
- Terminator: CRLF (`\r\n`)
- Encoding: ASCII lowercase commands

| Command | Meaning |
| --- | --- |
| `q6h2d` | auto forward |
| `q6h3d` | auto reverse |
| `q6h4d` | manual forward |
| `q6h5d` | manual reverse |
| `q6h6d` | stop |
| `q1hxxd` | speed integer |
| `q2hxxd` | speed decimal |
| `q3hHHd` | hour |
| `q4hMMd` | minute |
| `q5hSSd` | second |
| `q6h1d` | save |

Example settings for speed 15.37 mm/min and duration 30 sec:

```text
q1h15d
q2h37d
q3h00d
q4h00d
q5h30d
q6h1d
```

## Windows App Build

PyInstaller one-folder build:

```powershell
scripts\build_windows.bat
```

Generated kit:

```text
dist\A4PumpGUI\A4PumpGUI.exe
dist\A4PumpGUI\a4ctl\a4ctl.exe
dist\A4PumpGUI\config\
dist\A4PumpGUI\nis_cmd\
```

Notes:

- `A4PumpGUI.exe` is the GUI app.
- `a4ctl.exe` is the CLI app used by NIS `.cmd` wrappers.
- Rebuilding fills only missing external config files; it does not overwrite existing JSON.
- Bundled `_internal\default_config` is a first-run copy source only.
- `assets` are included in the build.
- `assets/icons/app.ico` is used as the executable icon if present.
- `pathlib` backport package can break PyInstaller. If needed, remove it with `pip uninstall pathlib` or `conda remove pathlib`.

## Quick Start: Source

PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m pytest
python run_gui.py
```

CLI source run:

```powershell
python -m syringe_perfusion.cli --help
python -m syringe_perfusion.cli list-ports
```

## Quick Start: Built App

GUI:

```powershell
dist\A4PumpGUI\A4PumpGUI.exe
```

CLI:

```powershell
dist\A4PumpGUI\a4ctl\a4ctl.exe config-path
dist\A4PumpGUI\a4ctl\a4ctl.exe list-ports
```

## Quick Start: CLI

Serial port一覧:

```powershell
python -m syringe_perfusion.cli list-ports
```

Fast-30 settingsを書き込む:

```powershell
python -m syringe_perfusion.cli write-profile --pump IN --profile fast30_1ml --save
```

保存済みFast-30 profileを開始:

```powershell
python -m syringe_perfusion.cli run-profile --pump IN --profile fast30_1ml
```

500 msのJog forward:

```powershell
python -m syringe_perfusion.cli jog --pump IN --direction forward --duration-ms 500
```

有効な全pumpを停止:

```powershell
python -m syringe_perfusion.cli stop-all
```

`--dry-run` を付けると、serial portを開かずにoutgoing commandsを確認できます。

## NIS-Elements Integration Summary

Detailed setup is documented in [docs/NIS_Elements_6_02.md](docs/NIS_Elements_6_02.md). The `.cmd` wrapper policy is documented in [nis_cmd/README.md](nis_cmd/README.md). Macro-only examples are in [docs/NIS_macro_examples.txt](docs/NIS_macro_examples.txt).

NIS-Elements 6.02では、次の形式で外部ファイルを実行します。

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed.cmd");
```

Replace `<A4PUMP_ROOT>` with the actual installation folder on the microscope PC.

This project uses NIS to call `.cmd` files. Each `.cmd` file then calls `a4ctl.exe` with an explicit `--config-dir`, so execution does not depend on the NIS current directory.

NIS `Int_ExecProgram` only launches an external file. NIS does not directly report whether the process started successfully or whether it has completed. Check `nis_logs/nis_exec.log` and `logs/a4pump_YYYYMMDD.csv` after execution. Log unification is future work.

Path and COM-port policy for committed documentation:

- Do not hard-code personal paths in committed documentation.
- Use `<A4PUMP_ROOT>` in README and docs.
- Local deployment paths should be kept only in local `.cmd` files or local notes that are not committed.
- The actual COM port should be configured in `config/pumps.json`.

Representative NIS macro examples:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed_after_300s.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_cancel_pending.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

各 `.cmd` はscript位置からROOTを解決し、`set "CFG=%ROOT%\config"` と `--config-dir "%CFG%"` を使用します。Windows batchの行継続 `^` は使用せず、1 a4ctl command = 1 line、CRLFです。tracked wrapperに個人パスやCOM番号は書きません。

`pump_start_pushpull_fast30.cmd` は非推奨です。LIVE legacy `pushpull` は安全のためnonzeroで拒否され、DRY-RUN診断だけを維持します。`pump_start_fast30.cmd` / `run-profile` は互換用ですが共有coordinatorで予約されます。新規NIS macroはarmed wrapperを使用してください。

Tracked wrapperは再現性のため `%ROOT%\config` を明示します。GUIで別のActive Configを選んでもwrapperは自動変更されません。Setupの `Copy NIS CFG line` を使ってローカル配布用wrapperを同じディレクトリへ合わせるか、標準 `%ROOT%\config` に戻してください。

Recommended acquisition mode:

- Use ND Acquisition Advanced.
- Select `Advanced for` Time Phase 2.
- Insert the macro in `Execute before Time phase`.
- Use two time phases when imaging should continue during stimulation.
- `pump_start_armed.cmd` starts the already-programmed ARMED plan immediately before Time Phase 2, and Time Phase 2 imaging continues.
- Use `pump_start_armed_after_300s.cmd` when the start must be scheduled without blocking NIS.

Alternative acquisition mode:

- Use three time phases.
- Set Phase 2 to `No Acquisition`.
- Insert the macro in `Execute before Time phase` for Phase 2.
- Use this when imaging should stop during external command execution, or when an explicit non-imaging phase is needed.

NIS external program launch has a small lag. Measure actual liquid arrival timing with dye and align analysis to the observed arrival frame.

## Fast-30 Profile

Fast-30 is a reference profile targeting 1 mL / 30 sec with the confirmed syringe.

- Syringe: Terumo SS-05LZ 5 mL Luer-lock
- Speed: 15.37 mm/min
- Duration: 30 sec
- Target volume: 1000 uL
- Measured mass: 1.001, 1.007, 0.994, 1.000, 1.007 g
- Average: about 1.002 g

Settings write commands:

```text
q1h15d
q2h37d
q3h00d
q4h00d
q5h30d
q6h1d
```

The compatibility wrapper can write Fast-30 before acquisition with:

```text
<A4PUMP_ROOT>\nis_cmd\pump_write_fast30.cmd
```

Profile writing does not start the pump by default. LIVE `Start after write` / `--start-after-write` is safety-disabled; use PROGRAM / ARM and a coordinated start. DRY-RUN remains available for command diagnostics.

## Single Pump Mode

GUI supports IN-only single pump operation.

- OUT disabled is the default for one-pump operation.
- OUT COM may be blank when OUT is disabled.
- OUT COM is required when OUT is enabled.
- Push-pull, OUT only, and Two forward require OUT enabled.
- STOP ALL skips disabled pumps.
- Recipe Builder validates disabled pump usage before dry-run and run.
- LIVE recipes reserve a shared run ID. Recipe waits are cancellable, every later pump START is re-authorized, and STOP ALL prevents subsequent recipe blocks from starting a pump.

Pump enable state is stored in `config/pumps.json` and can also be changed from the GUI.

## GUI layout

- **Experiment**: port scan、flow setpoint、量子化preview、PROGRAM / ARM BOTH、START ARMED、STOP ALL、共有runtime state。
- **Setup**: Active Configの完全パスとsource、CLI共有状態、NIS CFG、COM/baudrate/terminator/timeout、安全保存・Reload、接続テスト、Manual/Jog。
- **Advanced**: Profiles、Calculator、Recipes。低頻度項目はスクロール可能です。

STOP ALLは全画面共通の固定領域にあり、Escも維持します。900 x 600でもExperimentの主要操作が見えるよう、起動時画面をExperimentにしています。

GUIの `GUI START delay sec` が0ならSTART ARMEDは即時実行、0より大きければCLI `schedule-armed` と同じdetached schedulerを使用してPENDINGになります。GUIは待機中もブロックせず、run ID、予定時刻、概算残り時間を表示します。CLI `start-armed` は常に即時です。

## Recipe Builder

V3.2 Recipe Builder has three main areas:

- Block Library
- Recipe Steps
- Inspector

Recipe Steps uses step cards for editing and review. Recipes can be validated, dry-run, and run. Disabled pump validation runs before execution.

Available block types:

- `pump_start`
- `pump_stop`
- `manual_jog`
- `stop_all`
- `wait`
- `log_marker`
- `prompt_check`

OUT disabled時にOUTを使うrecipeは、実行前のvalidationでエラーになります。

## Logging

Current logging is intentionally split:

1. `nis_logs/nis_exec.log`
   - Created by `.cmd` wrappers.
   - Records NIS-side execution start/end and exit code.
2. `logs/a4pump_YYYYMMDD.csv`
   - Created by `a4ctl` and `A4PumpGUI`.
   - Records pump commands, profiles, dry-run, command hex, responses, recipe IDs, and block IDs.

Do not treat these as one combined log. Log unification is future work and is planned for a future version.

## Application Icon and Assets

V3.2 includes application icon and logo asset loading.

```text
assets/
  icons/
  logo/
```

PNG icon/logo files are loaded by the GUI when present. PyInstaller includes the `assets` directory and uses `assets/icons/app.ico` as the executable icon when present.

Recommended app icon direction:

- No text, letters, numbers, labels, or tiny UI details.
- Use a simplified syringe pump silhouette.
- Use a high-contrast design that remains recognizable at 32 x 32 px.
- Recommended master size: 1024 x 1024.
- Export PNG sizes under `assets/icons/` and a Windows ICO as `assets/icons/app.ico`.
- Put larger logo images under `assets/logo/`.

## Safety

- First test without syringe or with an empty syringe.
- Confirm the COM port before each experiment day.
- Write Fast-30 before acquisition.
- Confirm A4 LCD speed/time.
- Check tubing, priming, needle position, and waste path.
- Use STOP ALL and Esc.
- Measure actual liquid arrival delay using dye.
- NIS external program launch has a small lag.
- A4 `V` pin must not be connected to USB-TTL power.

## Project Structure

```text
syringe_perfusion/
  syringe_perfusion/
  config/
  recipes/
  assets/
  docs/
  nis_cmd/
  scripts/
  tests/
```

Main entry points:

- `run_gui.py`: GUI application
- `run_cli.py`: PyInstaller CLI entry point
- `python -m syringe_perfusion.cli`: source-run CLI

## Development Status

- Version: V3.2
- Tests: run `python -m pytest -q` to verify the current checkout
- GUI/CLI one-folder build and NIS wrapper DRY-RUN confirmed
- Live pump control and actual NIS `Int_ExecProgram` behavior require hardware validation
- Tested command behavior: lowercase ASCII with CRLF over 9600 baud USB-TTL UART
- Log unification pending

## Version History

- V1: serial command wrapper, config, CLI/GUI, logging.
- V2: Recipe Builder.
- V2.1: single-pump mode and settings writer.
- V3.0: left navigation and card UI.
- V3.1: UI polish.
- V3.2: icon/assets and NIS-ready Windows app.
- V3.3 or future: log unification.
