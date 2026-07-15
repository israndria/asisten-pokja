@echo off
cd /d "%~dp0"
git pull --ff-only origin master
if not exist "%~dp0ui_dpa.py" (
    echo Menunggu sinkronisasi ui_dpa.py...
    for /l %%i in (1,1,30) do (
        if exist "%~dp0ui_dpa.py" goto module_ready
        timeout /t 1 /nobreak >nul
    )
    echo GAGAL: ui_dpa.py belum tersedia.
    pause
    exit /b 1
)
:module_ready
set PYTHONPATH=%~dp0
C:\WinPython313\python\python.exe -m streamlit run "%~dp0app.py" --server.port 8502
pause
