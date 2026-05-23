# A4シリンジポンプ制御プロジェクト

## 概要

USB仮想COM経由でA4シリンジポンプ1台または2台を制御するPythonプロジェクトです。初期実装では、A4本体に手動保存済みの速度・時間条件を呼び出して開始・停止します。PCからA4本体へ速度・時間を書き込む機能は、実機でコマンド体系が完全確認されてから追加します。

GUIは `tkinter`、シリアル通信は `pyserial`、設定はJSONです。Nikon/NIS-Elementsから呼び出すためのCLIと、手動操作用GUIを分けています。

## A4接続

- 通信速度: `9600 baud`
- 開始 前進: `Q6H2D`
- 開始 後退: `Q6H3D`（実機確認が必要）
- 停止/緊急停止: `Q6H6D`
- コマンド末尾: `config/pumps.json` の `terminator` で変更可能
  - `""`
  - `"\\r"`
  - `"\\n"`
  - `"\\r\\n"`

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

GUIには4つのタブがあります。

- Pump: COMポート、terminator、dry-run、開始/停止、STOP ALL
- Syringe / Calculator: シリンジ選択と速度・時間・体積計算
- Profile: Fast-30、Fast-20、Gentle-60、Gentle-120、Drain-30の確認
- Run: Dish ID、Condition、Trigger source、IN only、OUT only、Push-pull、Two forward

GUI操作も `logs/a4pump_YYYYMMDD.csv` に記録されます。

## Nikon/NISから呼ぶ例

PyInstallerで作成した `a4ctl.exe` をNIS-Elements側から呼び出します。

```powershell
a4ctl.exe run-profile --pump IN --profile fast30_1ml --dish-id Dish001 --condition StimA --trigger-source NIS
```

または:

```powershell
a4ctl.exe pushpull --in-pump IN --out-pump OUT --profile-in fast30_1ml --profile-out drain30_1ml --out-delay 0.5 --dish-id Dish001 --condition StimA --trigger-source NIS
```

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
- A4が反応しない: `terminator` を `""`, `"\\r"`, `"\\n"`, `"\\r\\n"` で切り替えて確認してください。
- OUT後退が期待通りでない: `Q6H3D` は実機確認が必要です。必ず水または色素で流向を確認してください。
- ログが見つからない: 通常実行ではプロジェクトの `logs/`、exe化後は実行ファイル階層の `logs/` を確認してください。

## 将来拡張

A4への速度・時間自動設定は、以下コマンド体系が実機で完全確認されてから実装します。

- `Q1HxxD` 速度整数部
- `Q2HxxD` 速度小数部
- `Q3HxxD` 時
- `Q4HxxD` 分
- `Q5HxxD` 秒
- `Q6H1D` 保存

現時点では、速度・時間はA4本体側に手動保存し、PC側は開始・停止のみ送ります。
