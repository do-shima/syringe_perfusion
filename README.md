# A4シリンジポンプ制御プロジェクト

## 概要

USB仮想COM経由でA4シリンジポンプ1台または2台を制御するPythonプロジェクトです。初期実装では、A4本体に手動保存済みの速度・時間条件を呼び出して開始・停止します。PCからA4本体へ速度・時間を書き込む機能は、実機でコマンド体系が完全確認されてから追加します。

GUIは `tkinter`、シリアル通信は `pyserial`、設定はJSONです。Nikon/NIS-Elementsから呼び出すためのCLIと、手動操作用GUIを分けています。

## A4接続

- 通信速度: `9600 baud`
- 開始 前進: `q6h2d`
- 開始 後退: `q6h3d`
- manual forward: `q6h4d`
- manual reverse: `q6h5d`
- 停止/緊急停止: `q6h6d`
- コマンド末尾: CRLF (`\r\n`)

GUIとCLIは、送信時にCOMポートを開いてすぐ閉じます。これによりGUIとNIS呼び出しCLIがCOMポートを奪い合いにくくなります。

## COMポート確認

```powershell
python -m syringe_perfusion.cli list-ports
```

表示されたCOMポートを `config/pumps.json` の `IN` / `OUT` に設定します。

## 設定ファイル

設定は `config/` 以下にあります。

- `pumps.json`: ポンプ名、COMポート、baudrate、terminator、A4コマンド
- `syringes.json`: シリンジ径、校正済み `uL/mm`
- `profiles.json`: Fast-30などの運転条件
- `recipes.json`: 複数ポンプ動作の手順

PyInstallerでone-folder化した場合も、実行ファイル階層または同梱された `config/` を参照します。

## Fast-30条件

本命プロファイルは `fast30_1ml` です。

- 5 mL Terumo SS-05LZ Luer-lock syringe
- 15.37 mm/min
- 30 sec
- 実測: 1.001, 1.007, 0.994, 1.000, 1.007 g
- 平均: 約1.002 g

主ライン:

- A4 syringe pump
- 5 mL Luer-lock syringe
- R1-FL three-way stopcock
- SF-ET1020L22 extension tube
- BNG-18L bent needle
- LX-D35 holder
- 35 mm dish

## CLI使用例

ヘルプ:

```powershell
python -m syringe_perfusion.cli --help
```

計算:

```powershell
python -m syringe_perfusion.cli calc --syringe terumo_ss05lz_5ml --volume-ul 1000 --duration-s 30
```

INポンプを前進開始:

```powershell
python -m syringe_perfusion.cli send --pump IN --action start-forward --dish-id Dish001 --condition StimA --trigger-source Manual
```

Manual操作:

```powershell
python -m syringe_perfusion.cli send --pump IN --action manual-forward
python -m syringe_perfusion.cli send --pump IN --action manual-reverse
python -m syringe_perfusion.cli send --pump IN --action stop
```

Jog操作:

```powershell
python -m syringe_perfusion.cli jog --pump IN --direction forward --duration-ms 1000
python -m syringe_perfusion.cli jog --pump IN --direction reverse --duration-ms 1000
```

保存済みA4条件をFast-30として開始し、ログに条件情報を残す:

```powershell
python -m syringe_perfusion.cli run-profile --pump IN --profile fast30_1ml --dish-id Dish001 --condition StimA --trigger-source NIS
```

Push-pull:

```powershell
python -m syringe_perfusion.cli pushpull --in-pump IN --out-pump OUT --profile-in fast30_1ml --profile-out drain30_1ml --out-delay 0.5 --dish-id Dish001 --condition StimA --trigger-source NIS
```

緊急停止:

```powershell
python -m syringe_perfusion.cli stop-all
```

## GUI使用例

```powershell
python run_gui.py
```

GUIには5つのタブがあります。

- Pump: COMポート、dry-run、開始/停止、Manual / Jog、STOP ALL
- Syringe / Calculator: シリンジ選択と速度・時間・体積計算
- Profile: Fast-30、Fast-20、Gentle-60、Gentle-120、Drain-30の確認
- Run: Dish ID、Condition、Trigger source、IN only、OUT only、Push-pull、Two forward
- Recipe Builder: V2レシピの作成、dry-run、実行

GUI操作も `logs/a4pump_YYYYMMDD.csv` に記録されます。

PumpタブのManual / Jog:

- `Hold forward` / `Hold reverse`: ボタン押下時に `q6h4d` / `q6h5d`、ボタン解放またはボタン外への移動時に `q6h6d`
- `Stop`: 選択中ポンプに `q6h6d`
- `Jog forward` / `Jog reverse`: 指定msだけ `q6h4d` / `q6h5d` を送り、自動で `q6h6d`
- `Auto stop after ms`: Hold-to-runの保険停止タイマー
- Escキー: `STOP ALL`

初回はシリンジなし、または空シリンジで確認してください。実液体ラインでは、manual操作前に針位置、廃液ライン、閉塞がないことを確認してください。

## Nikon/NISから呼ぶ例

PyInstallerで作成した `a4ctl.exe` をNIS-Elements側から呼び出します。

```powershell
a4ctl.exe run-profile --pump IN --profile fast30_1ml --dish-id Dish001 --condition StimA --trigger-source NIS
```

または:

```powershell
a4ctl.exe pushpull --in-pump IN --out-pump OUT --profile-in fast30_1ml --profile-out drain30_1ml --out-delay 0.5 --dish-id Dish001 --condition StimA --trigger-source NIS
```

V2レシピを呼ぶ場合:

```powershell
a4ctl.exe run-recipe --recipe recipes\pushpull_fast30.json --dish-id Dish001 --condition StimA --trigger-source NIS --assume-yes
```

## V2 Recipe Builder

V2では、ブロックを縦に並べる方式のレシピビルダーを追加しています。Tkinter / ttkのみで実装しており、Qt、Electron、WebView、Blockly本体は使いません。ドラッグ＆ドロップではなく、`Move up` / `Move down` で順序を変更します。

利用できるブロック:

- `pump_start`: `IN` / `OUT` に `start_forward` または `start_reverse` を送信
- `pump_stop`: 指定ポンプに `q6h6d`
- `manual_jog`: `IN` / `OUT` に `q6h4d` または `q6h5d` を送り、指定ms後に `q6h6d`
- `stop_all`: 全ポンプに `q6h6d`
- `wait`: 指定秒数待つ
- `log_marker`: ハードウェア操作なしでログだけ記録
- `prompt_check`: GUIでは確認ダイアログ、CLIでは `--assume-yes` がない場合に標準入力で確認

GUIでは `Recipe Builder` タブからブロック追加、編集、上下移動、複製、削除、保存、読み込み、dry-run、実行ができます。Run前にはRecipe previewとチェックリストを表示します。OUT reverse / `start_reverse` を含む場合は警告を表示します。

## レシピJSON形式

レシピは `recipes/` にJSONとして保存します。

```json
{
  "schema_version": 2,
  "recipe_id": "pushpull_fast30_v1",
  "display_name": "Push-pull Fast-30",
  "description": "",
  "blocks": [
    {
      "id": "b001",
      "type": "pump_start",
      "pump": "IN",
      "action": "start_forward",
      "profile": "fast30_1ml",
      "note": "Stimulus injection"
    },
    {
      "id": "b002",
      "type": "wait",
      "duration_s": 0.5
    },
    {
      "id": "b003",
      "type": "pump_start",
      "pump": "OUT",
      "action": "start_reverse",
      "profile": "drain30_1ml",
      "note": "Waste suction"
    },
    {
      "id": "b004a",
      "type": "manual_jog",
      "pump": "IN",
      "direction": "forward",
      "duration_ms": 1000,
      "note": "Bounded manual jog"
    },
    {
      "id": "b004",
      "type": "wait",
      "duration_s": 35.0
    },
    {
      "id": "b005",
      "type": "stop_all",
      "note": "Safety stop"
    }
  ]
}
```

同梱サンプル:

- `recipes/in_fast30.json`
- `recipes/pushpull_fast30.json`

## V2 CLI

レシピ一覧:

```powershell
python -m syringe_perfusion.cli list-recipes
```

レシピ検証:

```powershell
python -m syringe_perfusion.cli validate-recipe --recipe recipes/pushpull_fast30.json
```

dry-run:

```powershell
python -m syringe_perfusion.cli run-recipe --recipe recipes/pushpull_fast30.json --dish-id Dish001 --condition StimA --trigger-source NIS --dry-run
```

実行:

```powershell
python -m syringe_perfusion.cli run-recipe --recipe recipes/pushpull_fast30.json --dish-id Dish001 --condition StimA --trigger-source NIS --assume-yes
```

`prompt_check` ブロックがある場合、`--assume-yes` を付けないCLI実行では標準入力で確認します。dry-runでは確認を省略します。

## GUIでのレシピ作成手順

1. `python run_gui.py` を起動します。
2. `Recipe Builder` タブを開きます。
3. 左のBlock paletteからブロックを追加します。
4. 中央のRecipe timelineでブロックを選択します。
5. 右のProperties editorで `pump`、`action`、`profile`、`duration_s`、`message`、`note` を編集し、`Apply changes` を押します。
6. `Move up` / `Move down` で順序を調整します。
7. `Dry-run` でログと実行順を確認します。
8. 実機実行前にRecipe previewとチェックリストを確認します。

## Safety stop

`STOP ALL` は確認ダイアログなしで即時実行します。Recipe BuilderタブではEscキーでも `STOP ALL` を呼びます。レシピ実行中に例外が出た場合、可能な範囲で全ポンプ停止を試みます。GUIはCOMポートを開きっぱなしにせず、送信時に開いて閉じます。

V2ログでは既存CSVに次の列を追加しています。

- `started_at`
- `ended_at`
- `recipe_id`
- `block_id`
- `block_type`
- `relative_time_s`
- `block_index`
- `mode`
- `jog_duration_ms`
- `response_hex`

## dry-run

実機なしでログとコマンドを確認できます。

```powershell
python -m syringe_perfusion.cli run-profile --pump IN --profile fast30_1ml --dry-run
```

dry-runではCOMポートを開かず、応答は `DRY_RUN` になります。

## PyInstallerでのビルド

one-folder形式でGUIとCLIを作成します。

```powershell
scripts\build_windows.bat
```

内部では次を実行します。

```powershell
pyinstaller --onedir --name A4PumpGUI --add-data "config;config" run_gui.py
pyinstaller --onedir --name a4ctl --add-data "config;config" run_cli.py
```

one-fileではなくone-folderを優先します。共用PCでトラブルが少なく、`config/` と `logs/` を扱いやすく、DLL展開の問題を避けやすいためです。

## トラブルシューティング

- `pyserial is required`: `pip install -r requirements.txt` を実行してください。
- COMポートが開けない: A4の電源、USB接続、デバイスマネージャーのCOM番号、他アプリがポートを掴んでいないかを確認してください。
- A4が反応しない: A4電源、COMポート、9600 baud / 8N1 / no flow control、CRLF終端を確認してください。
- OUT後退が期待通りでない: `q6h3d` / `q6h5d` は必ず水または色素で流向を確認してください。
- ログが見つからない: 通常実行ではプロジェクトの `logs/`、exe化後は実行ファイル階層の `logs/` を確認してください。

## 将来拡張

A4への速度・時間自動設定は、以下コマンド体系が実機で完全確認されてから実装します。

- `q1hxxd` 速度整数部
- `q2hxxd` 速度小数部
- `q3hxxd` 時
- `q4hxxd` 分
- `q5hxxd` 秒
- `q6h1d` 保存

現時点では、速度・時間はA4本体側に手動保存し、PC側は開始・停止のみ送ります。
