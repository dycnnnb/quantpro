@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
echo Starting QuantPro...
python -m src.web.app
pause
