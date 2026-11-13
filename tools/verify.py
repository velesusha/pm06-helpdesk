"""Run the actual test suite and save a machine-readable verification record."""
import contextlib
import io
import json
from pathlib import Path
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records=[]

    def addSuccess(self,test):
        super().addSuccess(test);self.records.append({'test':test.id(),'result':'passed'})

    def addFailure(self,test,err):
        super().addFailure(test,err);self.records.append({'test':test.id(),'result':'failed'})

    def addError(self,test,err):
        super().addError(test,err);self.records.append({'test':test.id(),'result':'error'})


suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
stream=io.StringIO();started=time.perf_counter()
with contextlib.redirect_stdout(io.StringIO()):
    result=unittest.TextTestRunner(stream=stream,resultclass=Result,verbosity=2).run(suite)
record={'checked_at':datetime.now(timezone(timedelta(hours=4))).isoformat(), 'database':'SQLite',
        'duration_seconds':round(time.perf_counter()-started,3),'tests_run':result.testsRun,
        'passed':result.wasSuccessful(),'tests':result.records,
        'sqlserver':'Not executed: SQL Server and ODBC driver unavailable on this machine.'}
out=ROOT/'reports';out.mkdir(exist_ok=True)
(out/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'verification.txt').write_text(stream.getvalue(),encoding='utf-8')
print(stream.getvalue());print('Saved reports/verification.json')
raise SystemExit(0 if result.wasSuccessful() else 1)
