@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 simple_chess.py --config ai_config.json
) else (
    python simple_chess.py --config ai_config.json
)
pause
