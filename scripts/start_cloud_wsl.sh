#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  /usr/bin/python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import cryptography' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements-cloud.txt
fi
if [[ ! -f .env.cloud ]]; then
  .venv/bin/python scripts/configure_cloud_local.py
fi

while IFS='=' read -r key value; do
  [[ "$key" =~ ^CLOUD_[A-Z0-9_]+$ ]] || continue
  export "$key=$value"
done < .env.cloud

missing=()
for key in CLOUD_TWITCH_CLIENT_ID CLOUD_TWITCH_CLIENT_SECRET CLOUD_ENCRYPTION_KEY CLOUD_COMMUNITY_OWNER_ID; do
  [[ -n "${!key:-}" ]] || missing+=("$key")
done
if ((${#missing[@]})); then
  echo "Cloud configuration is incomplete: ${missing[*]}"
  echo "Edit $PROJECT_DIR/.env.cloud, then run this script again."
  echo "Twitch redirect URI: http://127.0.0.1:8090/auth/callback"
  exit 2
fi

echo "Squat Capture cloud control panel: http://127.0.0.1:${CLOUD_PORT:-8090}/"
echo "Viewer Community page: http://127.0.0.1:${CLOUD_PORT:-8090}/viewer"
exec .venv/bin/python -m squat_capture.cloud
