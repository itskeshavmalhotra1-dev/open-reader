@echo off
setlocal
if "%~1"=="" (
    start "" /D "%~dp0" pythonw run_reader.py
) else (
    start "" /D "%~dp0" pythonw run_reader.py "%~1"
)
endlocal
