@echo off
setlocal
cd /d "%~dp0\.."

pyinstaller --onedir --name A4PumpGUI --add-data "config;config" --add-data "recipes;recipes" run_gui.py
if errorlevel 1 exit /b %errorlevel%

pyinstaller --onedir --name a4ctl --add-data "config;config" --add-data "recipes;recipes" run_cli.py
if errorlevel 1 exit /b %errorlevel%

echo Build completed.
