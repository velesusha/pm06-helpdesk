"""Check update, backup and recovery in a disposable SQL Server LocalDB instance."""
import csv
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def sql_string(value):
    return "N'" + str(value).replace("'", "''") + "'"


def control_rows(module):
    with module.Database() as db:
        rows = db.all('SELECT id,source_id,status,assignee_id FROM tickets ORDER BY id')
    return rows


def login_after_restore():
    server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        request = urllib.request.Request(
            f'http://127.0.0.1:{server.server_port}/api/login',
            data=json.dumps({'login': 'operator', 'password': app.DEMO_PASSWORD}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert json.load(response)['ok']
            return response.status
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def main():
    evidence = Path(sys.argv[1]).resolve()
    evidence.mkdir(parents=True)
    old_source = subprocess.check_output(['git', 'show', '3351c84b:app.py'], cwd=ROOT)
    old_path = evidence.parent / 'app_v10.py'
    old_path.write_bytes(old_source)
    spec = importlib.util.spec_from_file_location('app_v10', old_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    old.ROOT = ROOT
    old.VERSION = '1.0'

    connection = app.SQLSERVER.rstrip(';') + ';Database='
    if not app.SQLSERVER or 'LocalDB' not in app.SQLSERVER:
        raise SystemExit('A disposable LocalDB instance is required.')
    with closing(pyodbc.connect(connection + 'master', autocommit=True)) as master:
        master.execute('CREATE DATABASE [Pm06Helpdesk]')
        old.SQLSERVER = app.SQLSERVER = connection + 'Pm06Helpdesk'
        old.initialize()
        with old.Database() as db:
            user = db.one('SELECT id,role FROM users WHERE login=?', ('operator',))
            sample = (ROOT / 'data/leads.csv').read_text(encoding='utf-8-sig')
            imported = old.import_csv(db, sample, user)
        before = control_rows(old)
        assert imported['added'] == len(before) == 8
        with (evidence / 'control.csv').open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=list(before[0]), delimiter=';')
            writer.writeheader()
            writer.writerows(before)

        def backup(version):
            path = evidence / f'Pm06Helpdesk_v{version}.bak'
            disk = 'DISK=' + sql_string(path)
            cursor = master.execute(f'BACKUP DATABASE [Pm06Helpdesk] TO {disk} WITH COPY_ONLY, INIT, CHECKSUM')
            while cursor.nextset():
                pass
            cursor.execute(f'RESTORE VERIFYONLY FROM {disk} WITH CHECKSUM')
            while cursor.nextset():
                pass
            return disk

        backup('1_0')
        app.initialize()
        after = control_rows(app)
        assert after == before
        assert old.priority(True, 12)['code'] == 'normal'
        assert app.priority(True, 12)['code'] == 'critical'
        updated = backup('1_1')
        files = master.execute('RESTORE FILELISTONLY FROM ' + updated).fetchall()
        moves = []
        for item in files:
            extension = '.mdf' if item.Type == 'D' else '.ldf'
            path = evidence.parent / ('Pm06Helpdesk_Restored' + extension)
            moves.append(f'MOVE {sql_string(item.LogicalName)} TO {sql_string(path)}')
        began = time.perf_counter()
        cursor = master.execute('RESTORE DATABASE [Pm06Helpdesk_Restored] FROM ' + updated +
                                ' WITH CHECKSUM, RECOVERY, ' + ', '.join(moves))
        while cursor.nextset():
            pass
        app.SQLSERVER = connection + 'Pm06Helpdesk_Restored'
        restored = control_rows(app)
        assert restored == before
        status = login_after_restore()
        seconds = round(time.perf_counter() - began, 3)
        assert status == 200 and seconds <= 1800
        report = dict(engine=master.execute('SELECT @@VERSION').fetchval(), imported=len(before),
                      after_update=len(after), restored=len(restored),
                      control_rows_equal=True, priority_before='normal', priority_after='critical',
                      backup_verified_with_checksum=True, login_status=status, restore_to_login_seconds=seconds)
        output = json.dumps(report, ensure_ascii=False, indent=2)
        (evidence / 'sqlserver-results.json').write_text(output + '\n', encoding='utf-8')
        print(output)


if __name__ == '__main__':
    main()
