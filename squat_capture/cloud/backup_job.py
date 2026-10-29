"""Daily integrity-checked SQLite snapshots with bounded local retention."""
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from squat_capture.cloud.backup import backup


BACKUP_NAME = re.compile(r'^cloud-\d{8}T\d{6}Z\.sqlite3$')


def run_backup(source, directory, retention_days=7, now=None):
    if type(retention_days) is not int or not 2 <= retention_days <= 90:
        raise ValueError('Backup retention must be 2-90 days')
    source = Path(source).resolve()
    directory = Path(directory).resolve()
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError('Backup directory must be an existing absolute directory')
    now = time.time() if now is None else now
    stamp = datetime.fromtimestamp(now,timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = directory / f'cloud-{stamp}.sqlite3'
    backup(source,destination)

    cutoff = now - retention_days * 24 * 60 * 60
    removed = []
    for candidate in directory.iterdir():
        if (candidate == destination or candidate.is_symlink() or not candidate.is_file() or
                not BACKUP_NAME.fullmatch(candidate.name)):
            continue
        if candidate.stat().st_mtime < cutoff:
            candidate.unlink()
            removed.append(candidate.name)
    return destination, sorted(removed)


def main():
    directory = os.environ.get('CLOUD_BACKUP_DIRECTORY','')
    if not directory:
        raise SystemExit('CLOUD_BACKUP_DIRECTORY is required')
    try:
        retention = int(os.environ.get('CLOUD_BACKUP_RETENTION_DAYS','7'))
    except ValueError as error:
        raise SystemExit('CLOUD_BACKUP_RETENTION_DAYS must be a whole number') from error
    destination, removed = run_backup(os.environ.get('CLOUD_DATABASE','.cloud-data/cloud.sqlite3'),
                                      directory,retention)
    print(f'Backup completed and integrity checked: {destination.name}; expired snapshots removed: {len(removed)}')


if __name__ == '__main__':
    main()
