"""Explicit, non-overwriting SQLite backup. Does not upload or remove any files."""
import os
import sqlite3
import sys
from pathlib import Path


def backup(source, destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file():raise ValueError('Source database is missing')
    if source==destination:raise ValueError('Backup must use a new path')
    # Exclusive creation prevents accidental overwrite; a failed partial backup
    # remains for inspection and must not be treated as a successful snapshot.
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    dst=sqlite3.connect(destination)
    try:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed')
    finally:
        dst.close();src.close()


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m squat_capture.cloud.backup NEW_DESTINATION')
    backup(os.environ.get('CLOUD_DATABASE','.cloud-data/cloud.sqlite3'),sys.argv[1])
    print('Backup completed and integrity checked. Protect this file and the separate encryption key.')
