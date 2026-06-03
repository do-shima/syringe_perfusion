@echo off
setlocal
cd /d "%~dp0\.."

set ICON_ARG=
if exist "assets\icons\app.ico" set ICON_ARG=--icon "assets\icons\app.ico"

pyinstaller %ICON_ARG% --onedir --name A4PumpGUI --add-data "config;config" --add-data "recipes;recipes" --add-data "assets;assets" run_gui.py
if errorlevel 1 exit /b %errorlevel%

pyinstaller --onedir --name a4ctl --add-data "config;config" --add-data "recipes;recipes" --add-data "assets;assets" run_cli.py
if errorlevel 1 exit /b %errorlevel%

echo Build completed.
