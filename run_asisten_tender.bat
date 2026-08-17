@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0
set ASISTEN_INSTANCE=TENDER
set ASISTEN_FIXED_ROLE=POKJA
set SPSE_CDP_PORT=9223
if exist "C:\WinPython313\python\python.exe" (
    set PYTHON_EXE=C:\WinPython313\python\python.exe
) else (
    set PYTHON_EXE=%~dp0..\Runtime\WPy64-313110\python\python.exe
)
"%PYTHON_EXE%" -m streamlit run "%~dp0app.py" --server.port 8506
pause
