"""Create an ignored local cloud environment without printing secrets."""
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from squat_capture.app_config import APP_CONFIG


ENV_PATH = ROOT / '.env.cloud'
ORDER = (
    'CLOUD_DEV', 'CLOUD_ORIGIN', 'CLOUD_PORT', 'CLOUD_ALLOWED_USERS',
    'CLOUD_COMMUNITY_OWNER_ID', 'CLOUD_COMMUNITY_TIMEZONE',
    'CLOUD_TWITCH_CLIENT_ID', 'CLOUD_TWITCH_CLIENT_SECRET',
    'CLOUD_ENCRYPTION_KEY', 'CLOUD_DATABASE', 'CLOUD_ENABLE_EVENTS',
    'CLOUD_EVENTSUB_SECRET',
)


def read_values(path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in ORDER:
            values[key] = value
    return values


def main():
    saved = read_values(ENV_PATH)
    public = APP_CONFIG.public()
    owner = saved.get('CLOUD_COMMUNITY_OWNER_ID') or public.get('broadcaster_id', '')
    values = {
        'CLOUD_DEV': '1',
        'CLOUD_ORIGIN': 'http://127.0.0.1:8090',
        'CLOUD_PORT': '8090',
        'CLOUD_ALLOWED_USERS': owner,
        'CLOUD_COMMUNITY_OWNER_ID': owner,
        'CLOUD_COMMUNITY_TIMEZONE': 'America/Los_Angeles',
        'CLOUD_TWITCH_CLIENT_ID': '',
        'CLOUD_TWITCH_CLIENT_SECRET': '',
        'CLOUD_ENCRYPTION_KEY': Fernet.generate_key().decode(),
        'CLOUD_DATABASE': '.cloud-data/cloud.sqlite3',
        'CLOUD_ENABLE_EVENTS': '0',
        'CLOUD_EVENTSUB_SECRET': '',
    }
    for key in ORDER:
        if saved.get(key):
            values[key] = saved[key]
        elif os.environ.get(key):
            values[key] = os.environ[key]
    lines = [
        '# Local private cloud configuration. Ignored by Git; never share this file.',
        '# Twitch redirect URI: http://127.0.0.1:8090/auth/callback',
        *(f'{key}={values[key]}' for key in ORDER),
        '',
    ]
    ENV_PATH.write_text('\n'.join(lines), encoding='utf-8')
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass
    missing = [key for key in ('CLOUD_TWITCH_CLIENT_ID','CLOUD_TWITCH_CLIENT_SECRET') if not values[key]]
    login = public.get('broadcaster_login') or 'unknown'
    print(f'Prepared {ENV_PATH.name} for {login} ({owner or "missing owner ID"}).')
    if missing:
        print('Still required: ' + ', '.join(missing))
        print('Create a separate Twitch Confidential Web App with the redirect URI shown above.')
    else:
        print('Cloud credentials are present. Secrets were not displayed.')


if __name__ == '__main__':
    main()
