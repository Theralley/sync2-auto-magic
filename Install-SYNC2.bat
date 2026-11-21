@echo off
rem Windows: double-click this file to start the guided installer. It needs Python 3.9 or newer
rem and Docker Desktop. On a Mac use Install-SYNC2.command, on Linux install-sync2.sh.
setlocal
cd /d "%~dp0"
rem Text is read and written as UTF-8, as on the Mac and Linux, whatever language Windows has.
set PYTHONUTF8=1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto nopython
%PY% -m s2am wizard
echo.
pause
exit /b 0

:nopython
echo Python 3.9 or newer is missing. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in its installer, then try again.
pause
exit /b 1
