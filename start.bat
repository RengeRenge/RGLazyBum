@echo off
rem ---------------------------------------------------------------------------
rem RGLazyBum - source / debug launcher.
rem Normal way to run the tool is the packaged exe (build.bat output).
rem This script is for development: run from source with the venv.
rem
rem   start.bat              start tray mode (no console window)
rem   start.bat --console    console mode (Ctrl+C to stop)
rem
rem The listening port is not configurable: settings.CANDIDATE_PORTS is tried in
rem order and the first free one wins. Both this script and the phone app use that
rem same list, so nothing needs to be typed in.
rem ---------------------------------------------------------------------------
cd /d "%~dp0"

if "%~1"=="--addfw" goto addfw
if "%~1"=="--console" goto console

call :ensure_venv
if errorlevel 1 exit /b 1
rem The tray has its own firewall menu item, so nothing is prompted here.

start "" ".venv\Scripts\pythonw.exe" tray.py
exit /b 0

:console
call :ensure_venv
if errorlevel 1 exit /b 1

rem The source-mode firewall rule is named "RGLazyBum <port>", but the port is
rem only decided at runtime, so every candidate has to be open.
for /f "usebackq delims=" %%p in (`.venv\Scripts\python.exe -c "import settings;print(' '.join(map(str,settings.CANDIDATE_PORTS)))"`) do set "PORTS=%%p"
if "%PORTS%"=="" set "PORTS=8765"

call :ensure_firewall

".venv\Scripts\python.exe" server.py
echo.
echo Server stopped.
pause
exit /b 0

:ensure_venv
if exist ".venv\Scripts\python.exe" exit /b 0

echo.
echo [setup] First run: creating virtual environment...
python -m venv .venv
if errorlevel 1 goto failed

echo [setup] Installing dependencies (fast mirror)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
if errorlevel 1 goto failed
exit /b 0

:ensure_firewall
rem Source mode can only use a port-scoped rule: the venv python.exe is just a
rem launcher, the real listener is the base interpreter. Program-scoped rules
rem are used by the packaged exe instead (see firewall.py).
rem PORTS is a space-separated list of every candidate port, so open all of them.
set "MISSING="
for %%p in (%PORTS%) do (
  netsh advfirewall firewall show rule name="RGLazyBum %%p" >nul 2>&1
  if errorlevel 1 set "MISSING=1"
)
if not defined MISSING exit /b 0

echo.
echo [setup] Some candidate ports are not open in Windows Firewall yet.
echo         Asking for administrator rights - please click Yes.
echo         This is a one-time step.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '--addfw','%PORTS%'"
if errorlevel 1 goto fwmanual
exit /b 0

:fwmanual
echo.
echo [setup] Could not get administrator rights.
echo         Your phone will NOT be able to connect until those ports are allowed.
echo         Fix: use the tray menu item "allow phone access", or right-click
echo              start.bat and pick "Run as administrator" once.
echo.
exit /b 0

:addfw
rem %~2 is the whole space-separated candidate list, passed as one argument.
for %%p in (%~2) do (
  netsh advfirewall firewall add rule name="RGLazyBum %%p" dir=in action=allow protocol=TCP localport=%%p profile=any >nul 2>&1
)
exit /b 0

:failed
echo.
echo Setup failed. Please check:
echo   1. Python 3.10 or newer is installed, and "python" works in cmd.
echo   2. This computer can reach the internet (needed to download packages).
echo.
pause
exit /b 1
