import http.cookiejar
import json
import os
import shutil
import uuid
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
import app
import maintenance


class Client:
    def __init__(self, base):
        self.base, self.csrf = base, ''
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, method='GET', body=None, headers=None):
        h = {'Content-Type':'application/json', 'X-CSRF-Token': self.csrf, **(headers or {})}
        req = urllib.request.Request(self.base + '/api' + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            response = self.opener.open(req)
        except urllib.error.HTTPError as exc:
            response = exc
        raw = response.read().decode('utf-8-sig')
        data = json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
        return response.status, data

    def login(self, login='operator', password=app.DEMO_PASSWORD):
        status, data = self.request('/login','POST',dict(login=login,password=password))
        if status == 200:
            status, data = self.request('/me'); self.csrf = data['user']['csrf']
        return status, data


class HelpdeskTests(unittest.TestCase):
    def setUp(self):
        self.folder = app.ROOT / '.test-tmp' / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        app.DATA = self.folder
        app.SQLSERVER = ''
        app.Handler.attempts = {}
        app.initialize()
        self.server = app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.client = Client(self.base); self.client.login()
        self.sample = (app.ROOT/'data/leads.csv').read_text(encoding='utf-8')
        self.catalog = self.client.request('/catalog')[1]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        if not self.folder.resolve().is_relative_to((app.ROOT / '.test-tmp').resolve()):
            raise RuntimeError('Refusing to remove a directory outside the test workspace')
        shutil.rmtree(self.folder)

    def create(self, **changes):
        body=dict(subject='Проверка',description='Тестовая заявка',category_id=self.catalog['categories'][0]['id'],office='301',affected_users=1,service_unavailable=False)
        body.update(changes)
        return self.client.request('/tickets','POST',body)

    def test_01_import_and_repeat(self):
        status, result=self.client.request('/import','POST',{'content':self.sample})
        self.assertEqual((status,result['total'],result['added'],result['skipped'],result['rejected']),(200,10,8,1,1))
        result=self.client.request('/import','POST',{'content':self.sample})[1]
        self.assertEqual((result['added'],result['skipped'],result['rejected']),(0,9,1))
        tickets=self.client.request('/tickets')[1]['tickets']
        self.assertEqual(len(tickets),8)
        self.assertEqual(next(t['category'] for t in tickets if t['source_id']=='1006'),'ПО')

    def test_02_authentication(self):
        self.assertEqual(Client(self.base).request('/tickets')[0],401)
        self.assertEqual(Client(self.base).login(password='wrong')[0],401)
        self.assertEqual(Client(self.base).login('admin')[0],200)

    def test_03_password_hashing(self):
        encoded=app.password_hash('ExampleSecret!')
        self.assertNotIn('ExampleSecret!',encoded)
        self.assertTrue(app.password_ok('ExampleSecret!',encoded))
        self.assertFalse(app.password_ok('wrong',encoded))
        self.assertNotEqual(encoded,app.password_hash('ExampleSecret!'))

    def test_04_priority_boundary(self):
        for flags,expected in [((True,5),'critical'),((True,4),'high'),((False,5),'high'),((False,4),'normal')]:
            with self.subTest(flags=flags):self.assertEqual(app.priority(*flags)['code'],expected)

    def test_05_blank_subject_rejected(self):
        self.assertEqual(self.create(subject='   ')[0],400)
        self.assertEqual(self.create(subject=None)[0],400)
        self.assertEqual(len(self.client.request('/tickets')[1]['tickets']),0)

    def test_06_direct_close_rejected(self):
        tid=self.create()[1]['id']
        self.assertEqual(self.client.request(f'/tickets/{tid}','PATCH',{'status':'closed'})[0],400)
        self.assertEqual(self.client.request(f'/tickets/{tid}')[1]['ticket']['status'],'new')

    def test_07_status_filter(self):
        tid=self.create()[1]['id']
        self.assertEqual(len(self.client.request('/tickets?status=closed')[1]['tickets']),0)
        self.assertEqual(self.client.request('/tickets?status=new')[1]['tickets'][0]['id'],tid)

    def test_08_full_role_workflow(self):
        tid=self.create()[1]['id']; engineer=self.catalog['engineers'][0]['id']
        self.assertEqual(self.client.request(f'/tickets/{tid}','PATCH',{'assignee_id':engineer})[0],200)
        with app.Database() as db:login=db.one('SELECT login FROM users WHERE id=?',(engineer,))['login']
        worker=Client(self.base);worker.login(login)
        self.assertEqual(worker.request(f'/tickets/{tid}','PATCH',{'status':'in_progress'})[0],200)
        self.assertEqual(worker.request(f'/tickets/{tid}','PATCH',{'status':'resolved'})[0],200)
        self.assertEqual(worker.request(f'/tickets/{tid}','PATCH',{'status':'closed'})[0],403)
        self.assertEqual(self.client.request(f'/tickets/{tid}','PATCH',{'status':'closed'})[0],200)
        result=self.client.request(f'/tickets/{tid}')[1]
        self.assertEqual(result['ticket']['status'],'closed');self.assertEqual(len(result['history']),5)

    def test_09_foreign_ticket_forbidden(self):
        tid=self.create()[1]['id']; worker=Client(self.base);worker.login('engineer')
        self.assertEqual(worker.request(f'/tickets/{tid}')[0],403)
        self.assertEqual(worker.request(f'/tickets/{tid}','PATCH',{'status':'in_progress'})[0],403)
        self.assertEqual(worker.request('/tickets')[1]['tickets'],[])

    def test_10_engineer_limits(self):
        worker=Client(self.base);worker.login('engineer')
        for path,method,body in [('/users','GET',None),('/import','POST',{'content':self.sample}),('/tickets','POST',{})]:
            with self.subTest(path=path):self.assertEqual(worker.request(path,method,body)[0],403)

    def test_11_csrf_and_origin(self):
        self.assertEqual(self.client.request('/tickets','POST',{}, {'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.client.request('/tickets','POST',{}, {'Origin':'https://other.invalid'})[0],403)

    def test_12_admin_users_categories_and_revocation(self):
        admin=Client(self.base);admin.login('admin')
        status,result=admin.request('/users','POST',dict(login='newuser',full_name='Новый сотрудник',role='operator',password='LongPassword123!'))
        self.assertEqual(status,201); uid=result['id']
        user=Client(self.base);self.assertEqual(user.login('newuser','LongPassword123!')[0],200)
        self.assertEqual(admin.request(f'/users/{uid}','PATCH',{'active':0})[0],200)
        self.assertEqual(user.request('/me')[0],401)
        self.assertEqual(admin.request('/categories','POST',{'name':'Печать'})[0],201)
        self.assertEqual(admin.request('/categories','POST',{'name':' печать '})[0],409)

    def test_13_office_and_category_filters(self):
        self.client.request('/import','POST',{'content':self.sample})
        rows=self.client.request('/tickets?office=201')[1]['tickets']
        self.assertEqual([t['source_id'] for t in rows],['1001'])
        self.assertEqual(len(self.client.request('/tickets?q=1007')[1]['tickets']),1)
        category=next(c['id'] for c in self.catalog['categories'] if c['name']=='ПО')
        rows=self.client.request('/tickets?category_id='+str(category))[1]['tickets']
        self.assertEqual(len(rows),3)
        self.assertTrue(all(t['category']=='ПО' for t in rows))

    def test_14_backup_restore_comparison(self):
        self.client.request('/import','POST',{'content':self.sample})
        target=maintenance.backup()
        started=time.perf_counter()
        restored=maintenance.restore(target,app.DATA/'restored')
        self.assertEqual(maintenance.snapshot(target),maintenance.snapshot(restored))
        with closing(app.sqlite3.connect(restored)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
        with self.assertRaises(SystemExit):maintenance.restore(target,app.DATA/'restored')
        app.DATA=restored.parent
        restored_client=Client(self.base)
        self.assertEqual(restored_client.login()[0],200)
        self.assertEqual(len(restored_client.request('/tickets')[1]['tickets']),8)
        self.assertLess(time.perf_counter()-started,1800)

    def test_15_logout(self):
        self.assertEqual(self.client.request('/logout','POST',{})[0],200)
        self.assertEqual(self.client.request('/me')[0],401)

    def test_16_invalid_combined_update_rolls_back(self):
        admin=Client(self.base);admin.login('admin')
        with app.Database() as db:uid=db.one("SELECT id FROM users WHERE login='engineer2'")['id']
        self.assertEqual(admin.request(f'/users/{uid}','PATCH',{'active':0,'password':'short'})[0],400)
        with app.Database() as db:self.assertEqual(db.one('SELECT active FROM users WHERE id=?',(uid,))['active'],1)

    def test_17_no_arbitrary_fields(self):
        tid=self.create()[1]['id']
        self.assertEqual(self.client.request(f'/tickets/{tid}','PATCH',{'created_by':999})[0],400)
        self.assertEqual(self.create(affected_users=-1)[0],400)
        self.assertEqual(self.create(category_id=99999)[0],400)

    def test_18_cannot_work_unassigned(self):
        tid=self.create()[1]['id'];admin=Client(self.base);admin.login('admin')
        self.assertEqual(admin.request(f'/tickets/{tid}','PATCH',{'status':'in_progress'})[0],400)


if __name__=='__main__':unittest.main(verbosity=2)
