"""Local backup, restore and verification tools for the SQLite demonstration mode."""
import argparse
import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import app


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT id,source_id,status,assignee_id FROM tickets ORDER BY id').fetchall()


def backup():
    if app.SQLSERVER:
        raise SystemExit('SQL Server: use sql/backup_restore.sql in SSMS. SQLite copies are not SQL Server .bak files.')
    source = app.DATA / 'helpdesk.db'
    if not source.exists():
        raise SystemExit('Database does not exist. Start the application first.')
    folder = app.DATA / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    target = folder / f'helpdesk_{app.VERSION}_{stamp}.db'
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dest:
        src.backup(dest)
        check = dest.execute('PRAGMA integrity_check').fetchone()[0]
        rows = dest.execute('SELECT id,source_id,status,assignee_id FROM tickets ORDER BY id').fetchall()
    with target.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['id','source_id','status','assignee_id']); writer.writerows(rows)
    metadata = dict(version=app.VERSION, created_at=app.now(), database='SQLite', integrity=check,
                    count=len(rows), sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    target.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)
    return target


def restore(source, target_dir):
    source, target_dir = Path(source).resolve(), Path(target_dir).resolve()
    target = target_dir / 'helpdesk.db'
    if not source.is_file():
        raise SystemExit('Backup file not found.')
    if target.exists():
        raise SystemExit('Target already contains a database. Choose a new empty directory.')
    target_dir.mkdir(parents=True, exist_ok=True)
    # Refuse invalid files before creating the destination database.
    with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)) as src:
        if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Backup integrity check failed.')
        src.execute('SELECT COUNT(*) FROM tickets').fetchone()
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            # Restored copies require a fresh login.
            dst.execute('DELETE FROM sessions')
            dst.commit()
    print(json.dumps(dict(database=str(target), records_equal=snapshot(source)==snapshot(target)), ensure_ascii=False))
    return target


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command', required=True)
    sub.add_parser('backup')
    restore_cmd=sub.add_parser('restore')
    restore_cmd.add_argument('--file', required=True)
    restore_cmd.add_argument('--target-dir', required=True)
    compare=sub.add_parser('compare')
    compare.add_argument('first'); compare.add_argument('second')
    args=parser.parse_args()
    if args.command=='backup':backup()
    elif args.command=='restore':restore(args.file,args.target_dir)
    else:
        same=snapshot(args.first)==snapshot(args.second)
        print('MATCH' if same else 'DIFFERENT')
        raise SystemExit(0 if same else 1)


if __name__=='__main__':main()
