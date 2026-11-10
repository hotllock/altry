#!/usr/bin/env bash
# Linux / macOS: sets up a virtual environment on first run, then starts the server.
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "ffmpeg gerekli: https://ffmpeg.org/download.html"; exit 1; }
PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
echo "Telefondaki uygulamaya şu adresi yaz:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):8000"
exec .venv/bin/uvicorn altry.app:app --host 0.0.0.0 --port 8000
