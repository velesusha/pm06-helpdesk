"""Run against a locally running HTTPS instance and record only non-secret checks."""
import json
from pathlib import Path
import ssl
import urllib.request
from datetime import datetime, timezone, timedelta
ROOT=Path(__file__).resolve().parents[1]
ctx=ssl.create_default_context(cafile=str(ROOT/'data/certs/localhost.crt'))
req=urllib.request.Request('https://localhost:8443/api/login',
    data=json.dumps({'login':'operator','password':'Practice2026!'}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,context=ctx) as response:
    cookie=response.headers.get('Set-Cookie','')
    record={'checked_at':datetime.now(timezone(timedelta(hours=4))).isoformat(), 'status':response.status,
        'certificate_verified_against_local_certificate':True,'cookie_secure':'; Secure' in cookie,
        'cookie_httponly':'; HttpOnly' in cookie,'cookie_samesite_strict':'; SameSite=Strict' in cookie}
assert all(record[k] for k in ('certificate_verified_against_local_certificate','cookie_secure','cookie_httponly','cookie_samesite_strict'))
(ROOT/'reports/https.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print('HTTPS certificate and session cookie checks passed.')
