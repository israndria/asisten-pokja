@echo off
cd /d "%~dp0"
git pull origin master
set PYTHONPATH=%~dp0
start /min "Asisten Pokja" ..\V19_Scheduler\WPy64-313110\python\python.exe -m streamlit run app.py --server.port 8502
