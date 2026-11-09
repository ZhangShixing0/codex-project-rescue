@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys, tkinter; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 (
  py -3 launch.py
  goto finished
)
python -c "import sys, tkinter; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 goto missing_python
python launch.py
:finished
if errorlevel 1 (
  echo The program could not start. See the error above and README.md.
  pause
)
exit /b
:missing_python
echo Python 3.11+ with tkinter is required. See README.md for setup.
pause
exit /b 1
