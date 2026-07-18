@echo off
REM Odds auto-recorder runner (records even if the app is closed, as long as the PC is on).
REM Save a recording plan in Race Scanner first, then double-click this to start.
chcp 65001 >nul
cd /d "%~dp0"
echo Starting the odds auto-recorder. Press Ctrl+C in this window to stop.
python scripts\scheduled_odds_recorder.py
pause
