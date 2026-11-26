"""PM.06 helpdesk. Python 3.9+, SQLite demo or Microsoft SQL Server via ODBC."""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('HELPDESK_DATA', ROOT / 'data'))
SQLSERVER = os.environ.get('HELPDESK_SQLSERVER', '')
VERSION = os.environ.get('HELPDESK_VERSION', '1.1')
STATUSES = {'new': 'Новая', 'in_progress': 'В работе', 'resolved': 'Решена', 'closed': 'Закрыта'}
ROLES = {'operator': 'Оператор', 'engineer': 'Исполнитель', 'admin': 'Администратор'}
DEMO_PASSWORD = 'Practice2026!'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL UNIQUE,
 full_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('operator','engineer','admin')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT UNIQUE,
 subject TEXT NOT NULL CHECK(length(trim(subject))>0), description TEXT NOT NULL DEFAULT '',
 category_id INTEGER NOT NULL REFERENCES categories(id), office TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','in_progress','resolved','closed')),
 assignee_id INTEGER REFERENCES users(id), created_by INTEGER NOT NULL REFERENCES users(id),
 service_unavailable INTEGER NOT NULL DEFAULT 0 CHECK(service_unavailable IN (0,1)),
 affected_users INTEGER NOT NULL DEFAULT 1 CHECK(affected_users>=0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
 user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id),
 action TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metadata(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()
    return f'pbkdf2_sha256$260000${salt}${digest}'


def password_ok(password, encoded):
    try:
        algo, rounds, salt, expected = encoded.split('$')
        if algo != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


def priority(unavailable, affected):
    if unavailable and affected >= 5:
        return {'code': 'critical', 'name': 'Критический', 'reason': 'Сервис недоступен и затронуто не менее 5 пользователей.'}
    if unavailable or affected >= 5:
        return {'code': 'high', 'name': 'Высокий', 'reason': 'Сервис недоступен или затронуто не менее 5 пользователей.'}
    return {'code': 'normal', 'name': 'Обычный', 'reason': 'Сервис доступен и затронуто менее 5 пользователей.'}


class Database:
    def __enter__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        if SQLSERVER:
            import pyodbc
            self.conn = pyodbc.connect(SQLSERVER, timeout=10)
        else:
            self.conn = sqlite3.connect(DATA / 'helpdesk.db', timeout=20)
            self.conn.execute('PRAGMA foreign_keys=ON')
        return self

    def __exit__(self, kind, value, tb):
        try:
            self.conn.rollback() if kind else self.conn.commit()
        finally:
            self.conn.close()

    def execute(self, sql, args=()):
        return self.conn.cursor().execute(sql, tuple(args))

    def all(self, sql, args=()):
        cur = self.execute(sql, args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def insert(self, table, values):
        # Identifiers are internal constants; values always use bound parameters.
        columns = ','.join(values)
        placeholders = ','.join('?' for _ in values)
        output = ' OUTPUT INSERTED.id' if SQLSERVER else ''
        cur = self.execute(f'INSERT INTO {table} ({columns}){output} VALUES ({placeholders})', values.values())
        return int(cur.fetchone()[0]) if SQLSERVER else cur.lastrowid

    def audit(self, uid, action):
        self.insert('audit', {'user_id': uid, 'action': action, 'created_at': now()})


def initialize():
    with Database() as db:
        if SQLSERVER:
            schema = (ROOT / 'sql/schema_sqlserver.sql').read_text(encoding='utf-8')
            for batch in re.split(r'^GO\s*$', schema, flags=re.M | re.I):
                if batch.strip():
                    db.execute(batch)
        else:
            db.conn.executescript(SCHEMA)
        if not db.one('SELECT id FROM users'):
            for login, name, role in [('operator', 'Анна Оператор', 'operator'), ('engineer', 'Иван Исполнитель', 'engineer'),
                                      ('engineer2', 'Мария Исполнитель', 'engineer'), ('admin', 'Администратор стенда', 'admin')]:
                db.insert('users', dict(login=login, full_name=name, password_hash=password_hash(DEMO_PASSWORD), role=role, active=1))
        for name in ['ПО', 'Сеть', 'Оборудование']:
            if not db.one('SELECT id FROM categories WHERE name=?', (name,)):
                db.insert('categories', {'name': name})
        if not db.one('SELECT name FROM metadata WHERE name=?', ('schema_version',)):
            db.execute('INSERT INTO metadata(name,value) VALUES (?,?)', ('schema_version', VERSION))
        else:
            db.execute('UPDATE metadata SET value=? WHERE name=?', (VERSION, 'schema_version'))


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def text(value, label, limit, required=False):
    if not isinstance(value, str):
        raise Problem(400, f'{label}: требуется текст.')
    value = value.strip()
    if required and not value:
        raise Problem(400, f'{label}: заполните поле.')
    if len(value) > limit:
        raise Problem(400, f'{label}: максимум {limit} символов.')
    return value


def number(value, label, low=0, high=1000000):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise Problem(400, f'{label}: требуется целое число.')
    result = int(value)
    if not low <= result <= high:
        raise Problem(400, f'{label}: допустимо от {low} до {high}.')
    return result


def ticket_data(db, body):
    category_id = number(body.get('category_id', ''), 'Категория', 1)
    if not db.one('SELECT id FROM categories WHERE id=?', (category_id,)):
        raise Problem(400, 'Категория не найдена.')
    unavailable = body.get('service_unavailable', False)
    if unavailable not in (True, False, 0, 1):
        raise Problem(400, 'Недоступность сервиса: требуется 0 или 1.')
    return dict(subject=text(body.get('subject', ''), 'Тема', 180, True),
                description=text(body.get('description', ''), 'Описание', 6000),
                office=text(body.get('office', ''), 'Кабинет', 30), category_id=category_id,
                affected_users=number(body.get('affected_users', 1), 'Число пользователей', 0, 10000),
                service_unavailable=int(unavailable))


def create_ticket(db, body, user, source_id=None):
    values = ticket_data(db, body)
    values.update(source_id=source_id, status='new', assignee_id=None, created_by=user['id'], created_at=now(), updated_at=now())
    tid = db.insert('tickets', values)
    db.insert('history', dict(ticket_id=tid, user_id=user['id'], action='Заявка создана' + (' импортом CSV' if source_id else ''), created_at=now()))
    return tid


TICKET_SELECT = '''SELECT t.*, c.name AS category, u.full_name AS assignee,
 creator.full_name AS creator FROM tickets t JOIN categories c ON c.id=t.category_id
 LEFT JOIN users u ON u.id=t.assignee_id JOIN users creator ON creator.id=t.created_by'''


def decorate(row):
    row['priority'] = priority(row['service_unavailable'], row['affected_users'])
    return row


def get_ticket(db, tid, user):
    ticket = db.one(TICKET_SELECT + ' WHERE t.id=?', (tid,))
    if ticket is None:
        raise Problem(404, 'Заявка не найдена.')
    if user['role'] == 'engineer' and ticket['assignee_id'] != user['id']:
        raise Problem(403, 'Эта заявка назначена другому исполнителю.')
    return decorate(ticket)


def import_csv(db, content, user):
    try:
        content = content.lstrip('\ufeff')
        delimiter = ';' if ';' in content.splitlines()[0] else ','
        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
        required = {'source_id', 'subject', 'description', 'category', 'office', 'service_unavailable', 'affected_users'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise Problem(400, 'Проверьте заголовки CSV. Скачайте образец на странице импорта.')
        rows = list(reader)
    except (IndexError, csv.Error) as exc:
        raise Problem(400, 'Не удалось прочитать CSV.') from exc
    if len(rows) > 2000:
        raise Problem(400, 'В одном импорте допускается до 2000 строк.')
    results, added, skipped, rejected = [], 0, 0, 0
    for line, row in enumerate(rows, 2):
        try:
            source = text(row.get('source_id', ''), 'Исходный номер', 80, True)
            text(row.get('subject', ''), 'Тема', 180, True)
            if db.one('SELECT id FROM tickets WHERE source_id=?', (source,)):
                skipped += 1
                results.append(dict(line=line, source_id=source, result='Дубликат', detail='Пропущен'))
                continue
            category_name = text(row.get('category', ''), 'Категория', 80, True)
            categories = db.all('SELECT id,name FROM categories')
            cat = next((c for c in categories if c['name'].casefold() == category_name.casefold()), None)
            if cat is None:
                raise Problem(400, 'Неизвестная категория.')
            flag = text(row.get('service_unavailable', ''), 'Недоступность сервиса', 1, True)
            if flag not in ('0', '1'):
                raise Problem(400, 'Недоступность сервиса: требуется 0 или 1.')
            body = dict(row, category_id=cat['id'], service_unavailable=int(flag))
            create_ticket(db, body, user, source)
            added += 1
            results.append(dict(line=line, source_id=source, result='Добавлена', detail=cat['name']))
        except Problem as exc:
            rejected += 1
            results.append(dict(line=line, source_id=row.get('source_id', ''), result='Отклонена', detail=exc.message))
    db.audit(user['id'], f'Импорт CSV: добавлено {added}, дубликатов {skipped}, отклонено {rejected}')
    return dict(total=len(rows), added=added, skipped=skipped, rejected=rejected, rows=results)


class Handler(BaseHTTPRequestHandler):
    server_version = 'PM06Helpdesk/1.1'
    attempts = {}

    def log_message(self, fmt, *args):
        logging.info('%s %s', self.client_address[0], fmt % args)

    def reply(self, status, data, extra=None, content_type='application/json; charset=utf-8'):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2_000_000:
                raise Problem(413, 'Размер запроса должен быть от 1 байта до 2 МБ.')
            result = json.loads(self.rfile.read(size).decode('utf-8'))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeDecodeError):
            raise Problem(400, 'Ожидается объект JSON в UTF-8.')

    def session(self, db):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie['pm06_session'].value
        except Exception:
            raise Problem(401, 'Войдите в систему.')
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = db.one('''SELECT u.id,u.login,u.full_name,u.role,s.csrf FROM sessions s
            JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1''', (digest, int(time.time())))
        if not row:
            raise Problem(401, 'Сессия истекла. Войдите снова.')
        if self.command != 'GET' and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), row['csrf']):
            raise Problem(403, 'Защитный токен не совпал. Обновите страницу.')
        return row, digest

    def require(self, user, *roles):
        if user['role'] not in roles:
            raise Problem(403, 'Для вашей роли это действие недоступно.')

    def cookie(self, token, expires=28800):
        secure = '; Secure' if isinstance(self.connection, ssl.SSLSocket) else ''
        return f'pm06_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={expires}{secure}'

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PATCH(self):
        self.handle_request()

    def handle_request(self):
        try:
            path = urlsplit(self.path).path
            if self.command != 'GET':
                origin = self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    raise Problem(403, 'Запрос с другого сайта запрещён.')
            if path.startswith('/api/'):
                with Database() as db:
                    return self.api(db, path)
            if self.command != 'GET':
                raise Problem(405, 'Метод не поддерживается.')
            files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            if path == '/sample.csv':
                return self.reply(200, (ROOT / 'data/leads.csv').read_bytes(), {'Content-Disposition': 'attachment; filename=leads.csv'}, 'text/csv; charset=utf-8')
            if path not in files:
                raise Problem(404, 'Страница не найдена.')
            name, mime = files[path]
            return self.reply(200, (ROOT / 'web' / name).read_bytes(), content_type=mime)
        except Problem as exc:
            self.reply(exc.status, {'error': exc.message})
        except Exception:
            logging.exception('Request failed')
            self.reply(500, {'error': 'Ошибка сервера. Подробности записаны в журнал.'})

    def api(self, db, path):
        method = self.command
        if path == '/api/health' and method == 'GET':
            return self.reply(200, dict(ok=True, version=VERSION, database='SQL Server' if SQLSERVER else 'SQLite — демонстрационный режим'))
        if path == '/api/login' and method == 'POST':
            body = self.body()
            login = text(body.get('login', ''), 'Логин', 80, True)
            password = text(body.get('password', ''), 'Пароль', 200, True)
            key = (self.client_address[0], login.casefold())
            attempts = [t for t in self.attempts.get(key, []) if t > time.time() - 60]
            if len(attempts) >= 6:
                raise Problem(429, 'Слишком много попыток. Подождите минуту.')
            user = db.one('SELECT * FROM users WHERE login=? AND active=1', (login,))
            # Constant-cost hashing also for unknown users.
            valid = password_ok(password, user['password_hash'] if user else 'pbkdf2_sha256$260000$dummy$' + '0' * 64)
            if not user or not valid:
                self.attempts[key] = attempts + [time.time()]
                raise Problem(401, 'Неверный логин или пароль.')
            self.attempts.pop(key, None)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
            db.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES (?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, int(time.time()) + 28800))
            db.audit(user['id'], 'Успешный вход')
            return self.reply(200, {'ok': True}, {'Set-Cookie': self.cookie(token)})
        user, token_hash = self.session(db)
        if path == '/api/me' and method == 'GET':
            return self.reply(200, dict(user=user, version=VERSION, database='SQL Server' if SQLSERVER else 'SQLite · учебный стенд'))
        if path == '/api/logout' and method == 'POST':
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash,))
            return self.reply(200, {'ok': True}, {'Set-Cookie': self.cookie('', 0)})
        if path == '/api/catalog' and method == 'GET':
            return self.reply(200, dict(categories=db.all('SELECT * FROM categories ORDER BY name'),
                engineers=db.all("SELECT id,full_name FROM users WHERE role='engineer' AND active=1 ORDER BY full_name"), statuses=STATUSES, roles=ROLES))
        if path == '/api/tickets' and method == 'GET':
            params = parse_qs(urlsplit(self.path).query)
            where, args = ['1=1'], []
            if user['role'] == 'engineer':
                where.append('t.assignee_id=?'); args.append(user['id'])
            for field, col in [('status', 't.status'), ('category_id', 't.category_id'), ('office', 't.office')]:
                value = params.get(field, [''])[0]
                if value:
                    where.append(col + '=?'); args.append(value)
            q = params.get('q', [''])[0].strip()
            if q:
                where.append('(t.subject LIKE ? OR t.source_id LIKE ?)'); args.extend(['%' + q + '%'] * 2)
            rows = db.all(TICKET_SELECT + ' WHERE ' + ' AND '.join(where) + ' ORDER BY t.id DESC', args)
            return self.reply(200, {'tickets': [decorate(t) for t in rows]})
        if path == '/api/tickets' and method == 'POST':
            self.require(user, 'operator', 'admin')
            tid = create_ticket(db, self.body(), user)
            db.audit(user['id'], f'Создание заявки {tid}')
            return self.reply(201, {'id': tid})
        match = re.fullmatch(r'/api/tickets/(\d+)', path)
        if match:
            ticket = get_ticket(db, int(match[1]), user)
            if method == 'GET':
                history = db.all('SELECT h.*,u.full_name FROM history h JOIN users u ON u.id=h.user_id WHERE ticket_id=? ORDER BY h.id', (ticket['id'],))
                return self.reply(200, dict(ticket=ticket, history=history))
            if method == 'PATCH':
                return self.update_ticket(db, ticket, user)
        if path == '/api/import' and method == 'POST':
            self.require(user, 'operator', 'admin')
            content = text(self.body().get('content', ''), 'CSV', 1_500_000, True)
            return self.reply(200, import_csv(db, content, user))
        if path == '/api/export' and method == 'GET':
            self.require(user, 'operator', 'admin')
            rows = db.all('SELECT id,source_id,subject,status,assignee_id FROM tickets ORDER BY id')
            out = io.StringIO(newline='')
            writer = csv.DictWriter(out, fieldnames=['id','source_id','subject','status','assignee_id'], delimiter=';')
            writer.writeheader(); writer.writerows(rows)
            return self.reply(200, ('\ufeff' + out.getvalue()).encode('utf-8'), {'Content-Disposition': 'attachment; filename=control.csv'}, 'text/csv; charset=utf-8')
        if path == '/api/users':
            self.require(user, 'admin')
            if method == 'GET':
                return self.reply(200, {'users': db.all('SELECT id,login,full_name,role,active FROM users ORDER BY id')})
            if method == 'POST':
                return self.add_user(db, user)
        match = re.fullmatch(r'/api/users/(\d+)', path)
        if match and method == 'PATCH':
            self.require(user, 'admin')
            return self.update_user(db, user, int(match[1]))
        if path == '/api/categories' and method == 'POST':
            self.require(user, 'admin')
            name = text(self.body().get('name', ''), 'Категория', 80, True)
            if any(c['name'].casefold() == name.casefold() for c in db.all('SELECT name FROM categories')):
                raise Problem(409, 'Такая категория уже существует.')
            cid = db.insert('categories', {'name': name})
            db.audit(user['id'], f'Добавлена категория {name}')
            return self.reply(201, {'id': cid})
        if path == '/api/audit' and method == 'GET':
            self.require(user, 'admin')
            rows = db.all('SELECT a.*,u.full_name FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC')
            return self.reply(200, {'events': rows[:200]})
        raise Problem(404, 'Метод API не найден.')

    def update_ticket(self, db, ticket, user):
        body = self.body()
        if not body or set(body) - {'status', 'assignee_id'}:
            raise Problem(400, 'Можно изменить статус или исполнителя.')
        changes, messages = {}, []
        if 'assignee_id' in body:
            self.require(user, 'operator', 'admin')
            assignee = number(body['assignee_id'], 'Исполнитель', 1) if body['assignee_id'] is not None else None
            if ticket['status'] == 'closed':
                raise Problem(400, 'Закрытую заявку нельзя переназначить.')
            engineer = db.one("SELECT id,full_name FROM users WHERE id=? AND role='engineer' AND active=1", (assignee,)) if assignee else None
            if assignee and not engineer:
                raise Problem(400, 'Выберите действующего исполнителя.')
            if ticket['status'] in ('in_progress', 'resolved') and assignee is None:
                raise Problem(400, 'У заявки в работе должен быть исполнитель.')
            changes['assignee_id'] = assignee
            messages.append('Исполнитель: ' + (engineer['full_name'] if engineer else 'не назначен'))
        if 'status' in body:
            status = body['status']
            allowed = {'new': ['in_progress'], 'in_progress': ['resolved'], 'resolved': ['closed', 'in_progress'], 'closed': []}
            if status not in allowed[ticket['status']]:
                raise Problem(400, 'Недопустимый переход статуса. Порядок: Новая → В работе → Решена → Закрыта.')
            if user['role'] == 'operator' and not (ticket['status'] == 'resolved' and status == 'closed'):
                raise Problem(403, 'Рабочие статусы изменяет исполнитель. Оператор закрывает решённую заявку.')
            if status == 'closed' and user['role'] == 'engineer':
                raise Problem(403, 'Закрытие подтверждает оператор или администратор.')
            if status == 'in_progress' and not changes.get('assignee_id', ticket['assignee_id']):
                raise Problem(400, 'Сначала назначьте исполнителя.')
            changes['status'] = status
            messages.append(f"Статус: {STATUSES[ticket['status']]} → {STATUSES[status]}")
        changes['updated_at'] = now()
        # Compare previous state so two editors cannot silently overwrite a status.
        cur = db.execute('UPDATE tickets SET ' + ','.join(k + '=?' for k in changes) + ' WHERE id=? AND status=? AND updated_at=?',
                        [*changes.values(), ticket['id'], ticket['status'], ticket['updated_at']])
        if cur.rowcount == 0:
            raise Problem(409, 'Заявка уже изменена. Откройте её заново.')
        for message in messages:
            db.insert('history', dict(ticket_id=ticket['id'], user_id=user['id'], action=message, created_at=now()))
        db.audit(user['id'], f"Изменена заявка {ticket['id']}")
        return self.reply(200, {'ok': True})

    def add_user(self, db, user):
        body = self.body()
        login = text(body.get('login', ''), 'Логин', 80, True)
        if not re.fullmatch('[a-zA-Z0-9_.-]{3,80}', login):
            raise Problem(400, 'Логин: от 3 символов, латиница, цифры, точка, дефис или подчёркивание.')
        if db.one('SELECT id FROM users WHERE login=?', (login,)):
            raise Problem(409, 'Логин занят.')
        role = body.get('role')
        if role not in ROLES:
            raise Problem(400, 'Выберите роль.')
        password = text(body.get('password', ''), 'Пароль', 200, True)
        if len(password) < 10:
            raise Problem(400, 'Пароль должен содержать минимум 10 символов.')
        uid = db.insert('users', dict(login=login, full_name=text(body.get('full_name', ''), 'Имя', 150, True),
                      password_hash=password_hash(password), role=role, active=1))
        db.audit(user['id'], f'Создан пользователь {login}')
        return self.reply(201, {'id': uid})

    def update_user(self, db, user, uid):
        body = self.body()
        target = db.one('SELECT id,role,active FROM users WHERE id=?', (uid,))
        if not target:
            raise Problem(404, 'Пользователь не найден.')
        if not body or set(body) - {'active', 'password'}:
            raise Problem(400, 'Можно изменить пароль или активность.')
        if uid == user['id'] and body.get('active') in (0, False):
            raise Problem(400, 'Нельзя отключить собственную учётную запись.')
        if 'active' in body:
            active = number(body['active'], 'Активность', 0, 1)
            if not active and db.one("SELECT id FROM tickets WHERE assignee_id=? AND status<>'closed'", (uid,)):
                raise Problem(400, 'Сначала переназначьте незакрытые заявки этого пользователя.')
            db.execute('UPDATE users SET active=? WHERE id=?', (active, uid))
        if 'password' in body:
            password = text(body['password'], 'Пароль', 200, True)
            if len(password) < 10:
                raise Problem(400, 'Пароль должен содержать минимум 10 символов.')
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash(password), uid))
        db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        db.audit(user['id'], f'Изменён пользователь {uid}; сессии отозваны')
        return self.reply(200, {'ok': True})


def ensure_certificate():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import timedelta
    import ipaddress
    folder = DATA / 'certs'
    folder.mkdir(exist_ok=True, parents=True)
    cert_path, key_path = folder / 'localhost.crt', folder / 'localhost.key'
    if not cert_path.exists() or not key_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        stamp = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(stamp - timedelta(minutes=5))
            .not_valid_after(stamp + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--http', action='store_true', help='HTTP on loopback, for local preview only')
    parser.add_argument('--seed', action='store_true', help='Import sample CSV (idempotent)')
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(handlers=[logging.FileHandler(DATA / 'app.log', encoding='utf-8')], level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    initialize()
    if args.seed:
        with Database() as db:
            user = db.one("SELECT id,role FROM users WHERE login='operator'")
            result = import_csv(db, (ROOT / 'data/leads.csv').read_text(encoding='utf-8-sig'), user)
            print(f"Sample: added={result['added']}, skipped={result['skipped']}, rejected={result['rejected']}", flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    if not args.http:
        cert_path, key_path = ensure_certificate()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert_path, key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheme = 'http' if args.http else 'https'
    print(f'PM.06 Helpdesk {VERSION} · {"SQL Server" if SQLSERVER else "SQLite demo"}', flush=True)
    print(f'Local: {scheme}://localhost:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
