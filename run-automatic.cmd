@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" cli.py watch
) else (
  python cli.py watch
)
pause
