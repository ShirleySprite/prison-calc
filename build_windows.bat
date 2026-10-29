@echo off
setlocal
cd /d "%~dp0"

set "APP_NAME=The Only Software That Truly Cares When You Get Freed from Your Bullshit Work"

echo Installing build dependencies...
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed

echo Building standalone Windows executable...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "%APP_NAME%" --icon "assets\app_icon.ico" --add-data "assets;assets" --add-data "rendering\assets;rendering\assets" app.py
if errorlevel 1 goto :failed

echo.
echo Build complete:
echo %CD%\dist\%APP_NAME%.exe
exit /b 0

:failed
echo.
echo Build failed. Check the messages above.
exit /b 1
