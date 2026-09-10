#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

WSL_PYTHON="/usr/bin/python3"

if [[ ! -x "$WSL_PYTHON" ]]; then
  echo "Linux Python 3 is required inside WSL. Install it with:"
  echo "  sudo apt update && sudo apt install -y python3 python3-venv"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating local Python environment..."
  "$WSL_PYTHON" -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "Squat Capture control panel: http://127.0.0.1:8080/control"
exec .venv/bin/python twitch_eventsub_listener.py
