@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r tools\telegram\requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\telegram\telegram_local.py login
if errorlevel 1 goto failed
echo Local session saved. Automatic management is not running.
pause
exit /b 0
:failed
echo Setup stopped. Do not paste passwords or session data into a chat.
pause
exit /b 1

