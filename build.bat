@echo off
rem ---------------------------------------------------------------------------
rem RGLazyBum - build the onedir exe, then start it.
rem
rem   build.bat            build, then run dist\RGLazyBum\RGLazyBum.exe
rem   build.bat --clean    delete build\ and dist\ first, then build
rem   build.bat --nobuild  skip the build, just run the existing exe
rem
rem Note: onedir only. onefile would extract itself to a random temp folder,
rem which breaks the program-scoped Windows Firewall rule (see firewall.py).
rem ---------------------------------------------------------------------------
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto ensure_venv

if "%~1"=="--nobuild" goto run
if "%~1"=="--clean" goto clean

goto build

:clean
echo [build] Removing old build\ and dist\ ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:build
echo.
echo [build] Installing dependencies (fast mirror) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt pyinstaller
if errorlevel 1 goto failed

echo.
echo [build] Running PyInstaller ...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean RGLazyBum.spec
if errorlevel 1 goto failed

:run
if not exist "dist\RGLazyBum\RGLazyBum.exe" goto missing

echo.
echo [run] Starting dist\RGLazyBum\RGLazyBum.exe
start "" "dist\RGLazyBum\RGLazyBum.exe"
exit /b 0

:ensure_venv
echo.
echo [setup] First run: creating virtual environment ...
python -m venv .venv
if errorlevel 1 goto failed
echo [setup] Installing dependencies (fast mirror) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt pyinstaller
if errorlevel 1 goto failed
goto run

:missing
echo.
echo [error] dist\RGLazyBum\RGLazyBum.exe was not found.
echo         Run build.bat without --nobuild first.
pause
exit /b 1

:failed
echo.
echo [error] Build failed. Check the output above.
echo         1. Python 3.10 or newer must be installed and "python" must work.
echo         2. This computer needs internet access to download packages.
pause
exit /b 1
