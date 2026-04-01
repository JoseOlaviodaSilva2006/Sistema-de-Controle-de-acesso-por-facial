@echo off
chcp 65001 > nul
setlocal

set "LAUNCHER=launcher_ui.py"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%LAUNCHER%"
) else (
    start "" python "%LAUNCHER%"
)

endlocal
