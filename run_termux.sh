#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null 2>&1 || { echo "ثبّت FFmpeg أولاً: pkg update -y && pkg install ffmpeg python -y"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ثبّت Python أولاً: pkg install python -y"; exit 1; }
pkill -f "local_server.py" 2>/dev/null || true
python3 local_server.py
