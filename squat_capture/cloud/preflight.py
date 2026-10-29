"""Fail-closed production-beta configuration checks without printing secrets."""
import ipaddress
import os
import sqlite3
import stat
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

from squat_capture.cloud.server import Settings


PLACEHOLDERS = {'test', 'missing', 'change-me', 'changeme', 'replace-me', 'secret', 'your-secret'}


def _placeholder(value):
    normalized = value.strip().lower()
    return not normalized or normalized in PLACEHOLDERS or normalized.startswith(('your_', 'your-', 'example'))


def _public_hostname(hostname):
    if not hostname or hostname in ('localhost',) or hostname.endswith(('.local', '.invalid')):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return address.is_global


def inspect_environment(environ=None, platform=None):
    env = os.environ if environ is None else environ
    platform = os.name if platform is None else platform
    checks = []

    def add(ok, label, detail):
        checks.append(('PASS' if ok else 'FAIL', label, detail))

    try:
        settings = Settings.from_environment() if environ is None else Settings(
            env.get('CLOUD_ORIGIN',''),env.get('CLOUD_TWITCH_CLIENT_ID',''),
            env.get('CLOUD_TWITCH_CLIENT_SECRET',''),env.get('CLOUD_ENCRYPTION_KEY',''),
            env.get('CLOUD_DATABASE','.cloud-data/cloud.sqlite3'),int(env.get('CLOUD_PORT','8090')),
            env.get('CLOUD_DEV') == '1',env.get('CLOUD_EVENTSUB_SECRET',''),
            env.get('CLOUD_ENABLE_EVENTS') == '1',env.get('CLOUD_ALLOWED_USERS',''),
            env.get('CLOUD_COMMUNITY_OWNER_ID',''),env.get('CLOUD_COMMUNITY_TIMEZONE','America/Los_Angeles'))
    except Exception as error:
        return [('FAIL','configuration',str(error))]

    origin = urlsplit(settings.origin)
    add(not settings.development,'runtime mode','CLOUD_DEV must be 0 for a public beta')
    add(origin.scheme == 'https' and origin.port in (None,443),'public origin','Use HTTPS on the standard public port')
    add(_public_hostname(origin.hostname),'public hostname','Hostname must not be loopback, private, .local or .invalid')
    add(1024 <= settings.port <= 65535,'loopback port','Application port is in the unprivileged range')
    add(not _placeholder(settings.client_id),'Twitch client ID','Configured (value hidden)')
    add(not _placeholder(settings.client_secret),'Twitch client secret','Configured (value hidden)')
    try:
        Fernet(settings.encryption_key.encode())
        valid_key = True
    except Exception:
        valid_key = False
    add(valid_key,'encryption key','Valid Fernet key (value hidden)')

    allowed = [value.strip() for value in settings.allowed_users.split(',') if value.strip()]
    add(bool(allowed) and all(value.isdecimal() for value in allowed),'operator allowlist',
        'At least one numeric broadcaster user ID is required')
    add(bool(settings.community_owner_id),'community owner','Numeric Twitch owner ID is configured')
    add(bool(settings.community_owner_id) and settings.community_owner_id in allowed,'owner admission',
        'Community owner must also be in CLOUD_ALLOWED_USERS')
    try:
        ZoneInfo(settings.community_timezone)
        valid_timezone = True
    except Exception:
        valid_timezone = False
    add(valid_timezone,'daily timezone','Valid IANA timezone')

    database = Path(settings.database)
    add(database.is_absolute(),'database path','Production database path must be absolute')
    parent = database.parent
    add(parent.is_dir(),'database directory','Parent directory must already exist')
    if parent.is_dir() and platform == 'posix':
        add(stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,'database directory permissions',
            'Group/other access must be disabled (mode 0700)')
    if database.exists():
        try:
            with sqlite3.connect(f'file:{database.as_posix()}?mode=ro',uri=True) as db:
                integrity = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            add(integrity,'database integrity','SQLite integrity_check returned ok')
        except Exception:
            add(False,'database integrity','Existing database could not be opened read-only')
    else:
        checks.append(('WARN','database bootstrap','Database will be created on first successful start'))

    backup_directory = Path(env.get('CLOUD_BACKUP_DIRECTORY',''))
    add(backup_directory.is_absolute() and backup_directory.is_dir(),'backup directory',
        'Existing absolute directory is required for the daily backup timer')
    if backup_directory.is_absolute() and backup_directory.is_dir() and platform == 'posix':
        add(stat.S_IMODE(backup_directory.stat().st_mode) & 0o077 == 0,'backup directory permissions',
            'Group/other access must be disabled (mode 0700)')
    try:
        retention = int(env.get('CLOUD_BACKUP_RETENTION_DAYS','7'))
    except ValueError:
        retention = 0
    add(2 <= retention <= 90,'backup retention','Retention must be between 2 and 90 days')

    add(not settings.enable_events or bool(settings.eventsub_secret),'EventSub secret',
        'EventSub disabled for Viewer beta' if not settings.enable_events else 'Configured (value hidden)')
    return checks


def main():
    checks = inspect_environment()
    for level,label,detail in checks:
        print(f'{level:4}  {label}: {detail}')
    failures = sum(level == 'FAIL' for level,_,_ in checks)
    if failures:
        print(f'NOT READY: {failures} production check(s) failed.')
        raise SystemExit(1)
    print('READY: production-beta configuration passed local preflight.')


if __name__ == '__main__':
    main()
