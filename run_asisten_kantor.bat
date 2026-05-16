@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0
C:\WinPython313\python\python.exe -m streamlit run app.py --server.port 8502
pause
