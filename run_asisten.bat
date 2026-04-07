@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0
..\V19_Scheduler\WPy64-313110\python\python.exe -m streamlit run app.py --server.port 8502
pause
