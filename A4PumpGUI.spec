# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

build_info = Path('build/generated/build_info.json')
build_datas = [(str(build_info), '.')] if build_info.is_file() else []

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'default_config'), ('recipes', 'recipes'), ('assets', 'assets'), *build_datas],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='A4PumpGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icons\\app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='A4PumpGUI',
)
