"""Demonstrate real v1.0 -> v1.1 data preservation with isolated SQLite data."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import shutil
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app
import maintenance

git='git'
work=ROOT/'.test-tmp'/('upgrade-'+uuid.uuid4().hex)
work.mkdir(parents=True)
old_file=work/'app_v10.py'
old_file.write_bytes(subprocess.check_output([git,'show','v1.0:app.py'],cwd=ROOT))
spec=importlib.util.spec_from_file_location('pm06_v10',old_file)
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
old.DATA=work/'data';old.SQLSERVER='';old.initialize()
with old.Database() as db:
    operator=db.one("SELECT id,role FROM users WHERE login='operator'")
    imported=old.import_csv(db,(ROOT/'data/leads.csv').read_text(encoding='utf-8'),operator)
before=maintenance.snapshot(old.DATA/'helpdesk.db')
evidence=ROOT/'reports/backup-evidence';evidence.mkdir(exist_ok=True)
with closing(sqlite3.connect(old.DATA/'helpdesk.db')) as source, closing(sqlite3.connect(evidence/'v1_0.db')) as target:source.backup(target)
app.DATA=old.DATA;app.SQLSERVER='';app.initialize()
after=maintenance.snapshot(app.DATA/'helpdesk.db')
assert before==after
assert old.priority(True,12)['code']=='normal'
assert app.priority(True,12)['code']=='critical'
with closing(sqlite3.connect(app.DATA/'helpdesk.db')) as source, closing(sqlite3.connect(evidence/'v1_1.db')) as target:source.backup(target)
started=time.perf_counter()
restored=maintenance.restore(evidence/'v1_1.db',work/'restored')
assert maintenance.snapshot(restored)==before
record={'database':'SQLite','from_version':'1.0','to_version':'1.1','imported':imported['added'],
    'before_count':len(before),'after_count':len(after),'control_rows_equal':before==after,
    'priority_before':old.priority(True,12),'priority_after':app.priority(True,12),
    'restore_and_compare_seconds':round(time.perf_counter()-started,3),
    'restored_rows_equal':maintenance.snapshot(restored)==before,
    'sqlserver':'Not executed. Repeat on SQL Server using SSMS.'}
(ROOT/'reports/upgrade.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False,indent=2))
if work.resolve().parent != (ROOT/'.test-tmp').resolve():
    raise RuntimeError('Refusing cleanup outside the project test directory')
shutil.rmtree(work)
