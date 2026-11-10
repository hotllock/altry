@echo off
rem Windows: sets up a virtual environment on first run, then starts the server.
cd /d "%~dp0"
where ffmpeg >nul 2>nul || (echo ffmpeg gerekli: winget install ffmpeg & pause & exit /b 1)
if not exist .venv (
  py -3.11 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
echo Telefondaki uygulamaya bilgisayarin yerel IP adresini yaz, ornek: http://192.168.1.20:8000
ipconfig | findstr /c:"IPv4"
.venv\Scripts\uvicorn altry.app:app --host 0.0.0.0 --port 8000
