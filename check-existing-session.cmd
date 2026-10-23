@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check Pyrogram==2.0.106
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\telegram\check_existing_session.py
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Connection not confirmed. Do not paste the session or login codes into a chat.
pause
exit /b 1
