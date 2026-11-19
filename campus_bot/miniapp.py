"""Private Telegram Mini App sharing the bot's SQLite database."""
import asyncio
import base64
from http.cookies import SimpleCookie
import secrets
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import re
from pathlib import Path
import threading
import time
from urllib.parse import parse_qsl, urlsplit, parse_qs
from uuid import uuid4
from . import hackathons, health, web_login
from .mail import masked
from .models import clock
from .schedule import Schedule
from .storage import Store
from .weather import Weather
from .daily_plan import priority_text
from .access import allowed_ids

log = logging.getLogger(__name__)
APP_TASK_DAYS = 60


def done_days(moments, tz):
    """Local calendar days on which something was finished, for the streak."""
    days = set()
    for value in moments:
        try:
            days.add(datetime.fromisoformat(value).astimezone(tz).date().isoformat() if len(value) > 10 else value[:10])
        except ValueError:
            continue
    return sorted(days)

STATIC = Path(__file__).resolve().parent / 'web'
STATIC_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
                '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json'}
# Scripts only from this server and Telegram's SDK: injected markup cannot run code.
# No frame-ancestors: Telegram Web shows the Mini App inside its own frame.
CONTENT_POLICY = ("default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
                  "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")


def static_file(url_path):
    """(file, content type) for a request path under web/, or None.

    Paths are not percent-decoded, dotfiles and unknown types are refused and the
    resolved file must stay inside web/.
    """
    relative = 'index.html' if url_path in ('', '/') else url_path.removeprefix('/')
    parts = relative.split('/')
    if '\\' in relative or any(not part or part.startswith('.') for part in parts):
        return None
    path = (STATIC / relative).resolve()
    kind = STATIC_TYPES.get(path.suffix.lower())
    if not kind or STATIC.resolve() not in path.parents or not path.is_file():
        return None
    return path, kind
SESSION_COOKIE = '__Secure-campus_session'
# On its own subdomain the app lives at "/", where the stricter __Host- prefix is
# allowed: the browser then refuses a cookie set by any other subdomain.
HOST_COOKIE = '__Host-campus_session'
SESSION_SECONDS = 8*3600


def cookie_settings(url=None, kind='campus_session'):
    """(cookie name, path) for the address the Mini App is served from."""
    path = urlsplit(os.getenv('MINI_APP_URL', '') if url is None else url).path or '/'
    return ('__Host-' if path == '/' else '__Secure-') + kind, path


class AttemptLimit:
    """At most `limit` login attempts per window for the whole app (one owner, a few devices)."""

    def __init__(self, limit=20, window=600, clock=time.monotonic):
        self.limit, self.window, self.clock, self.times = limit, window, clock, []
        self.lock = threading.Lock()

    def allow(self):
        now = self.clock()
        with self.lock:
            self.times = [t for t in self.times if now - t < self.window]
            if len(self.times) >= self.limit:
                return False
            self.times.append(now)
            return True


def session_token(token, owner_id, now=None):
    payload = f'{owner_id}:{int(time.time() if now is None else now)+SESSION_SECONDS}:{secrets.token_hex(16)}'
    signature=hmac.new(token.encode(),b'campus-session:'+payload.encode(),hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((payload+':'+signature).encode()).decode().rstrip('=')


def verify_session(value, token, owner_id, now=None):
    try:
        decoded=base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode()
        owner,expires,nonce,signature=decoded.split(':')
        payload=f'{owner}:{expires}:{nonce}'
        expected=hmac.new(token.encode(),b'campus-session:'+payload.encode(),hashlib.sha256).hexdigest()
        current=time.time() if now is None else now
        return bool(owner_id and int(owner)==owner_id and current<int(expires)<=current+SESSION_SECONDS
                    and len(nonce)==32 and hmac.compare_digest(signature,expected))
    except (ValueError,UnicodeError,TypeError):
        return False


def verify_init_data(raw, token, owner_id, now=None, authorized=None, *, public_mode=False, max_age=3600):
    if not raw or len(raw) > 12000:
        raise PermissionError('Откройте приложение через меню Telegram-бота.')
    pairs = parse_qsl(raw, keep_blank_values=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise PermissionError('Повторяющиеся поля')
    received = fields.pop('hash', '')
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, '\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, signature):
        raise PermissionError('Неверная подпись Telegram')
    try:
        age = (time.time() if now is None else now) - int(fields.get('auth_date','0'))
        actor = json.loads(fields.get('user','{}'))['id']
    except (TypeError, ValueError, KeyError):
        raise PermissionError('Не удалось определить аккаунт Telegram.') from None
    if age < -30 or (max_age is not None and age > max_age):
        raise PermissionError('Сессия истекла. Откройте приложение заново.')
    if type(actor) is not int or not 0 < actor < 2**52:
        raise PermissionError('Не удалось определить аккаунт Telegram.')
    if not public_mode and (not owner_id or actor not in (authorized if authorized is not None else {owner_id})):
        raise PermissionError('Это личное приложение владельца.')
    return actor


def session_actor(value, token, authorized):
    try:
        raw=base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode()
        actor=int(raw.split(':',1)[0])
        return actor if (authorized is None or actor in authorized) and verify_session(value,token,actor) else None
    except (ValueError,UnicodeError,TypeError):
        return None


def title(value):
    if not isinstance(value,str) or not 1 <= len(value.strip()) <= 300:
        raise ValueError('Название: 1–300 символов')
    return value.strip()


def moment(value,tz):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


class App:
    def __init__(self,config,telegram=None):
        self.config = config
        self.login_attempts = AttemptLimit()
        self.telegram = telegram
        # Website back-off shared by all requests (each request builds its own Schedule).
        self.retry_after = {}

    def health(self):
        latency = self.telegram.latency() if self.telegram else None
        return health.report(self.config.data_dir/'bot.sqlite3', latency=latency)

    async def state(self,store,first,last):
        schedule = Schedule(store,self.config,cache_first=True,retry_after=self.retry_after,parallel_weeks=True)
        monday = first - timedelta(days=first.weekday())
        mondays = [monday + timedelta(weeks=i) for i in range((last - monday).days // 7 + 1)]
        weeks = dict(zip(mondays, await asyncio.gather(*(schedule.university(day) for day in mondays))))
        events,notes = {},[]
        day = first
        while day <= last:
            rows,note,_ = await schedule.day(day, week=weeks[day - timedelta(days=day.weekday())])
            if note and note not in notes:
                notes.append(note)
            for e in rows:
                key = e.uid+'|'+e.start.date().isoformat()
                row = asdict(e)
                row.update(start=e.start.isoformat(),end=e.end.isoformat(),key=key,done=store.checked(key))
                if e.source == 'university':
                    row['attendance'] = store.attendance(key)
                    row['done'] = row['attendance'] == 'present'
                events[key] = row
            day += timedelta(days=1)
        now = datetime.now(self.config.timezone)
        dropped = {p['id'] for p in store.projects() if p.get('status')=='dropped'}
        # Finished tasks older than 60 days stay in the database but no longer travel to the app.
        since = (now - timedelta(days=APP_TASK_DAYS)).isoformat()
        return dict(events=list(events.values()),tasks=[t for t in store.app_tasks(since) if t['project'] not in dropped],
                    done_days=done_days(store.done_moments(),self.config.timezone),
                    rules=store.rules(),group=store.get('group_name'),notes=notes,
                    weather=await Weather(store,self.config.timezone).today(refresh=False),
                    weather_brief=Weather(store,self.config.timezone).brief(),
                    settings={k:store.get(k) for k in ('digest_times','weather_times','notifications')},
                    hackathons=hackathons.overview(store,now),clashes=hackathons.clash_lines(store,now),
                    statuses=hackathons.STATUSES,kinds=hackathons.KINDS,mail=self.mail(store),
                    wellness=self.wellness_card(store), public_mode=self.config.public_mode)

    def wellness_card(self,store):
        from .wellness import Wellness
        try:
            return Wellness(store,self.config.timezone).today_card()
        except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:  # a broken journal row must not hide the calendar
            log.warning('wellness card skipped: %s',type(exc).__name__)
            return None

    def mail(self,store):
        configured = bool(self.config.mail_user and self.config.mail_password)
        return dict(configured=configured,enabled=store.get('mail_enabled',True),checked=store.get('mail_checked'),
                    address=masked(self.config.mail_user) if configured else '',error=store.get('mail_error'))

    def project(self,store,body):
        uid = body.get('id') or 'h-'+uuid4().hex[:6]
        if not hackathons.PROJECT_ID.fullmatch(uid) or body.get('status') not in hackathons.STATUSES or body.get('kind') not in hackathons.KINDS:
            raise ValueError('Проверьте статус и тип')
        links = body.get('links',[])
        if not isinstance(links,list) or len(links)>8 or any(not isinstance(l.get('url'),str) or len(l['url'])>500
                                                             or not l['url'].startswith(('https://','http://')) for l in links):
            raise ValueError('До восьми ссылок http(s)')
        text = lambda name,limit: str(body.get(name) or '').strip()[:limit]
        store.put_project(dict(id=uid,title=title(body['title']),kind=body['kind'],status=body['status'],organizer=text('organizer',200),
                               role=text('role',60),summary=text('summary',1000),prize=text('prize',300),
                               links=[dict(title=title(str(l.get('title') or 'Ссылка'))[:60],url=l['url']) for l in links]))
        return uid

    def stage(self,store,body):
        tz = self.config.timezone
        project,kind = body['project'],body['kind']
        if not store.project(project) or kind not in ('task','event','allday'):
            raise ValueError('Неизвестный хакатон или тип этапа')
        if kind == 'allday':
            days = int(body.get('days',1))
            if not 1 <= days <= 14:
                raise ValueError('От 1 до 14 дней')
            start,duration = datetime.combine(date.fromisoformat(body['date']),datetime.min.time(),tzinfo=tz),days*1440
        else:
            start,duration = moment(body['start'],tz),int(body.get('duration',60)) if kind == 'event' else 0
            if kind == 'event' and not 5 <= duration <= 1440:
                raise ValueError('Длительность: 5–1440 минут')
        row = ('task' if kind == 'task' else 'event',title(body['title']),start.isoformat(),duration,
               str(body.get('note') or '').strip()[:500],int(kind == 'allday'))
        if body.get('id'):
            with store.db:
                store.db.execute('UPDATE items SET kind=?,title=?,due=?,duration=?,note=?,all_day=? WHERE id=? AND project=?',
                                 row+(int(body['id']),project))
        else:
            store.add_item(row[0],row[1],row[2],row[3],project=project,note=row[4],all_day=row[5])

    def mutate(self,store,action,body):
        tz = self.config.timezone
        if action == 'calendar-import':
            from . import calendar_import
            source, events = calendar_import.fetch(body.get('url'), datetime.now(tz))
            counts = calendar_import.apply(store, source, events)
            return {**counts, 'message': calendar_import.summary(counts)}
        if action in ('wellness-recipe-link','wellness-recipe-link-delete'):
            from . import recipe_links
            if action=='wellness-recipe-link-delete':
                return recipe_links.remove(store,body.get('id'))
            return recipe_links.add(store,body.get('url'),body.get('title',''),datetime.now(tz))
        if action.startswith(('wellness-','workout-')):
            from .wellness import Wellness
            return Wellness(store,tz).mutate(action,body)
        if action in ('salary-extra', 'salary-extra-delete'):
            from . import salary
            if action == 'salary-extra-delete':
                return salary.remove_extra(store, body.get('id'))
            return salary.add_extra(store, body.get('month'), body.get('count'), body.get('rub'), body.get('note', ''),body.get('reference'))
        if action == 'salary-settings':
            enabled=body.get('enabled');time=clock(body.get('time','21:00'))
            if type(enabled) is not bool:raise ValueError('Укажите включение сводки')
            store.set('salary_report_time',time);store.set('salary_daily_report',enabled)
            return dict(ok=True)
        if action == 'billing-refresh':
            if body.get('month'):
                from .salary import month_key
                month=month_key(body['month'])
                store.set('salary_month_requests',list(dict.fromkeys([month]+store.get('salary_month_requests',[])))[:4])
            store.set('reollity_refresh_requested',True)
        elif action == 'billing-rate':
            from .tutoring import price
            student=next((s for s in store.students() if s['id']==body['id']),None)
            if not student:raise ValueError('Ученик не найден')
            month=date.fromisoformat(body['month']+'-01').strftime('%Y-%m')
            student.setdefault('rates',{})[month]=price(str(body['price']))
            store.put_student(student)
        elif action == 'billing-student':
            from .income import valid_share
            from .tutoring import price
            student=next((s for s in store.students() if s['id']==body['id']),None)
            if not student:raise ValueError('Ученик не найден')
            rate='' if body.get('rate') is None else str(body['rate']).strip()
            if rate:
                student['rate']=price(rate)
                # The permanent price applies from the shown month on: drop month prices that would hide it.
                month=str(body.get('month') or '')
                if re.fullmatch(r'\d{4}-\d{2}',month):
                    student['rates']={k:v for k,v in student.get('rates',{}).items() if k<month}
            else: student.pop('rate',None)
            if body.get('share') in (None,''): student.pop('share',None)
            else: student['share']=valid_share(body['share'])
            store.put_student(student)
        elif action == 'billing-defaults':
            from .income import valid_share
            from .tutoring import price
            store.set('tutoring_default_rate',price(str(body['rate'])))
            store.set('tutoring_share',valid_share(body['share']))
        elif action == 'quick-task':
            from .quick import parse_quick
            task=parse_quick(body.get('text'),datetime.now(tz))
            store.add_item('task',task['title'],task['due'],0,task['recurrence'],all_day=task['all_day'],
                           priority=task['priority'])
            return {'ok':True,'task':task}
        elif action == 'attendance':
            key, status = body.get('key'), body.get('status')
            if not isinstance(key,str) or len(key)>150 or not re.fullmatch(
                    r'(?:uni:\d+|uni-extra:[A-Za-z0-9_-]+)\|\d{4}-\d{2}-\d{2}',key):
                raise ValueError('Выберите вузовскую пару')
            day = date.fromisoformat(key.rsplit('|',1)[1])
            if day > datetime.now(tz).date() or status not in ('present','absent','pending'):
                raise ValueError('Отметка доступна для сегодняшних и прошедших пар')
            store.set_attendance(key,status)
        elif action == 'check':
            if type(body['done']) is not bool or not isinstance(body['key'],str) or len(body['key'])>150:
                raise ValueError('Неверная отметка')
            store.check(body['key'],body['done'])
        elif action == 'task-check':
            if type(body['done']) is not bool:
                raise ValueError('Неверная отметка')
            store.set_task_status(int(body['id']),'done' if body['done'] else 'pending')
        elif action == 'task-status':
            store.set_task_status(int(body['id']),body['status'])
        elif action in ('task','event'):
            start = moment(body['start'],tz)
            duration = int(body.get('duration',120)) if action == 'event' else 0
            if action == 'event' and not 5 <= duration <= 1440:
                raise ValueError('Длительность: 5–1440 минут')
            kind = 'event' if action == 'event' else 'task'
            text,parsed_priority = priority_text(title(body['title']))
            priority=max(parsed_priority,int(body.get('priority',0)))
            if priority not in (0,1) or ('all_day' in body and type(body['all_day']) is not bool):
                raise ValueError('Проверьте важность и время задачи')
            if kind=='task' and body.get('all_day'):
                start=start.replace(hour=23,minute=59,second=0,microsecond=0)
            if body.get('id'):
                existing=next((r for r in store.items(kind,include_done=True) if r['id']==int(body['id'])),None)
                if kind=='task' and existing:
                    duration=existing['duration']
                    if existing['is_group']:
                        store.move(existing['id'],start.isoformat())
                with store.db:
                    store.db.execute('UPDATE items SET title=?,due=?,duration=?,all_day=?,priority=?,note=? WHERE id=? AND kind=?',
                                     (text,start.isoformat(),duration,int(body.get('all_day',existing['all_day'] if existing else False)),
                                      max(parsed_priority,int(body.get('priority',existing['priority'] if existing else 0))),
                                      str(body.get('note',existing['note'] if existing else ''))[:500],int(body['id']),kind))
                if kind=='task' and existing and 'priority' in body:
                    store.set_priority(existing['id'],max(parsed_priority,int(body['priority'])))
                if kind=='task' and existing and 'recurrence' in body:
                    if body['recurrence'] not in ('once','daily','weekdays','weekly'):
                        raise ValueError('Неизвестное повторение')
                    if body['recurrence']!='once' and (existing['parent_id'] or existing['project'] or existing['is_group']):
                        raise ValueError('Повтор доступен только для обычной задачи')
                    with store.db:
                        store.db.execute('UPDATE items SET recurrence=? WHERE id=?',(body['recurrence'],existing['id']))
            else:
                repeat=body.get('recurrence','once') if kind=='task' else 'once'
                if repeat not in ('once','daily','weekdays','weekly'):
                    raise ValueError('Неизвестное повторение')
                store.add_item(kind,text,start.isoformat(),duration,repeat,all_day=bool(body.get('all_day',False)),
                               priority=priority,note=str(body.get('note',''))[:500])
        elif action == 'override':
            key = body['key']
            start,end = moment(body['start'],tz),moment(body['end'],tz)
            start_only = any(key == 'uni-extra:'+r['id']+'|'+start.date().isoformat()
                             and not r.get('end') and r['group_id'] == store.get('group_id')
                             for r in store.get('university_extras', []))
            valid_duration = timedelta(minutes=5)<=end-start<=timedelta(days=1) or (start_only and end==start)
            if len(key)>150 or start.date() != date.fromisoformat(key.rsplit('|',1)[1]) or not valid_duration:
                raise ValueError('Измените время внутри выбранного дня, длительность 5–1440 минут')
            store.put_override(key,dict(title=title(body['title']),start=start.isoformat(),end=end.isoformat(),cancelled=bool(body.get('cancelled',False))))
        elif action == 'reset-override':
            with store.db:
                store.db.execute('DELETE FROM overrides WHERE key=?',(body['key'],))
        elif action == 'delete-task':
            store.delete_task(int(body['id']))
        elif action == 'rule':
            repeat=body['cycle']
            if repeat not in ('once','daily','weekdays','all','a','b'):
                raise ValueError('Выберите повторение')
            days = list(range(7)) if repeat=='daily' else list(range(5)) if repeat=='weekdays' else sorted(set(body.get('weekdays',[])))
            duration = int(body['duration_minutes'])
            if (repeat!='once' and not days) or any(type(d) is not int or not 0<=d<=6 for d in days) or not 5<=duration<=1440:
                raise ValueError('Проверьте дни, цикл и длительность')
            rule=dict(id=body.get('id') or 'custom-'+uuid4().hex[:8],weekdays=days,time=clock(body['time']),
                      duration_minutes=duration,cycle=repeat,title=title(body['title']),note=str(body.get('note','')).strip()[:500])
            old = next((r for r in store.rules() if r['id'] == rule['id']), {})
            if old.get('student_ids'):
                from .tutoring import people, person_key
                rule['student_ids'] = sorted({person_key(n) for n in people(rule['title'])}) or old['student_ids']
            if repeat=='once':
                rule['date']=date.fromisoformat(body['date']).isoformat()
            else:
                for field in ('start_date','end_date'):
                    if body.get(field):rule[field]=date.fromisoformat(body[field]).isoformat()
                if rule.get('start_date') and rule.get('end_date') and rule['end_date']<rule['start_date']:
                    raise ValueError('Окончание периода раньше начала')
            store.put_rule(rule)
        elif action == 'delete-rule':
            store.delete_rule(body['id'])
        elif action == 'project':
            return {'ok':True,'id':self.project(store,body)}
        elif action == 'hack-status':
            project = store.project(body['id'])
            if not project or body['status'] not in hackathons.STATUSES:
                raise ValueError('Неверный статус')
            project['status'] = body['status']
            store.put_project(project)
        elif action == 'delete-project':
            store.delete_project(body['id'])
        elif action == 'stage':
            self.stage(store,body)
        elif action == 'stage-check':
            if type(body['done']) is not bool:
                raise ValueError('Неверная отметка')
            item = next((i for i in store.items(include_done=True) if i['id'] == int(body['id']) and i['project']),None)
            if not item:
                raise ValueError('Этап не найден')
            hackathons.set_done(store,item,body['done'])
        elif action == 'delete-stage':
            with store.db:
                store.db.execute('DELETE FROM items WHERE id=? AND project IS NOT NULL',(int(body['id']),))
        elif action == 'settings':
            for name in ('digest_times','weather_times'):
                if name in body:
                    if not isinstance(body[name],list) or len(body[name])>6:
                        raise ValueError('До шести отправок')
                    store.set(name,sorted({clock(t) for t in body[name]}))
            if 'mail_enabled' in body:
                if type(body['mail_enabled']) is not bool:
                    raise ValueError('Неверная настройка')
                store.set('mail_enabled',body['mail_enabled'])
            if 'notifications' in body:
                if type(body['notifications']) is not bool:
                    raise ValueError('Неверная настройка')
                store.set('notifications',body['notifications'])
            if 'subgroup' in body:
                if self.config.public_mode:
                    raise ValueError('Используйте ID группы Cube.')
                if str(body['subgroup']) not in ('1','2'):
                    raise ValueError('Подгруппа — 1 или 2')
                store.set('group_id',int(body['subgroup']))
                store.set('group_name','Группа '+str(body['subgroup']))
            if 'group_id' in body and self.config.public_mode:
                from .profiles import set_group
                set_group(store,body['group_id'],body.get('group_name'))
            if 'cycle_anchor' in body:
                anchor=date.fromisoformat(str(body['cycle_anchor']))
                if anchor.weekday()!=0:
                    raise ValueError('Начало недели A — понедельник')
                store.set('cycle_anchor',anchor.isoformat())
        else:
            raise ValueError('Неизвестное действие')
        return {'ok':True}

    def handler(self):
        app = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def respond(self,status,data,kind='application/json; charset=utf-8',headers=()):
                payload = json.dumps(data,ensure_ascii=False).encode() if 'json' in kind and not isinstance(data,bytes) else data
                self.send_response(status)
                if getattr(self,'new_session',None):
                    name,path=cookie_settings()
                    cookie=f'{name}={self.new_session}; Path={path}; Max-Age={SESSION_SECONDS}; Secure; HttpOnly; SameSite=Strict'
                    self.send_header('Set-Cookie',cookie)
                web=getattr(self,'web_cookie',None)
                if web is not None:
                    name,path=cookie_settings(kind='campus_web')
                    age=web_login.session_seconds(os.getenv('MINI_APP_URL','')) if web else 0
                    self.send_header('Set-Cookie',f'{name}={web}; Path={path}; Max-Age={age}; Secure; HttpOnly; SameSite=Strict')
                extra=dict(headers)
                for k,v in [('Content-Type',kind),('Content-Length',str(len(payload))),
                            ('Cache-Control',extra.pop('Cache-Control','no-store')),
                            ('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),*extra.items()]:
                    self.send_header(k,v)
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                route = urlsplit(self.path)
                if route.path == '/health':
                    report = app.health()
                    # Details (version, uptime, Telegram state) only for probes inside the container.
                    if self.client_address[0] not in ('127.0.0.1', '::1'):
                        report = {'status': report['status']}
                    return self.respond(200 if report['status'] == 'ok' else 503, report)
                if route.path.startswith('/api/'):
                    if route.path not in ('/api/state','/api/billing','/api/salary','/api/study','/api/wellness','/api/recipes','/api/assistant'):
                        return self.respond(404,{'error':'Не найдено'})
                    return self.api(route.path.removeprefix('/api/'),parse_qs(route.query))
                found = static_file(route.path)
                if not found:
                    return self.respond(404,{'error':'Не найдено'})
                path,kind = found
                page = kind.startswith('text/html')
                # The page always comes fresh; scripts and styles are revalidated on every open.
                headers = [('Cache-Control','no-store' if page else 'no-cache')]
                if page:
                    headers.append(('Content-Security-Policy',CONTENT_POLICY))
                self.respond(200,path.read_bytes(),kind,headers)

            def do_POST(self):
                path = urlsplit(self.path).path
                if not path.startswith('/api/'):
                    return self.respond(404,{'error':'Не найдено'})
                try:
                    size = int(self.headers.get('Content-Length','0'))
                    if not 0<size<=16000:
                        raise ValueError()
                    body = json.loads(self.rfile.read(size))
                except (ValueError,TypeError):
                    return self.respond(400,{'error':'Неверный запрос'})
                self.api(path[5:],body)

            def api(self,action,body):
                store = None
                try:
                    self.new_session=None
                    self.web_cookie=None
                    cookies=SimpleCookie()
                    try:cookies.load(self.headers.get('Cookie',''))
                    except Exception:pass
                    # Cookies count only with this header: another site cannot add it to a request.
                    trusted=self.headers.get('X-Campus-Session')=='1'
                    value=cookies.get(cookie_settings()[0])
                    web=cookies.get(cookie_settings(kind='campus_web')[0])
                    web_token=web.value if web and trusted else None
                    request_app=app
                    if app.config.public_mode:
                        from .profiles import Profiles
                        if action in ('login','web-sessions','web-logout','web-logout-all'):
                            raise PermissionError('Откройте приложение через Telegram.')
                        cookie_actor = session_actor(value.value,app.config.token,None) if trusted and value else None
                        actor = cookie_actor
                        signed=self.headers.get('X-Telegram-Init-Data','')
                        if signed:
                            try:
                                actor=verify_init_data(signed,app.config.token,0,public_mode=True)
                            except PermissionError:
                                # An expired Telegram payload can only resume the same account's signed session.
                                if not cookie_actor or verify_init_data(
                                    signed,app.config.token,0,public_mode=True,max_age=None
                                ) != cookie_actor:
                                    raise
                        if not actor:
                            raise PermissionError('Откройте приложение через Telegram.')
                        config,store=Profiles(app.config).open(actor)
                        request_app=App(config)
                        authorized={actor}
                        web_token=None
                        if signed and cookie_actor != actor:
                            self.new_session=session_token(config.token,actor)
                    else:
                        store=Store(app.config.data_dir/'bot.sqlite3')
                        authorized=allowed_ids(store,app.config.owner_id)
                    if action=='login':
                        if not trusted or not web_login.available(os.getenv('MINI_APP_URL','')):
                            raise PermissionError('Вход из браузера сейчас недоступен.')
                        try:
                            self.web_cookie,_=web_login.redeem(store,body.get('token'),authorized,
                                                               self.headers.get('User-Agent',''),
                                                               lifetime=web_login.session_seconds(os.getenv('MINI_APP_URL','')))
                        except PermissionError:
                            # Only failures count, so nobody can lock the owner's valid link out.
                            if not app.login_attempts.allow():
                                raise PermissionError('Слишком много неудачных попыток. Получите новую ссылку через /web.') from None
                            raise
                        return self.respond(200,{'ok':True})
                    if not app.config.public_mode:
                        actor=(trusted and value and session_actor(value.value,app.config.token,authorized)) or None
                        if not actor and web_token:
                            actor=web_login.session_actor(store,web_token,authorized)
                        if not actor:
                            actor=verify_init_data(self.headers.get('X-Telegram-Init-Data',''),app.config.token,
                                                   app.config.owner_id,authorized=authorized)
                            self.new_session=session_token(app.config.token,actor)
                    scoped=request_app.config
                    if action=='session':
                        return self.respond(200,{'ok':True})
                    if action in ('web-sessions','web-logout','web-logout-all'):
                        if action=='web-logout' and web_token:
                            web_login.revoke(store,actor,token=web_token);self.web_cookie=''
                        elif action=='web-logout-all':
                            web_login.revoke(store,actor,everywhere=True);self.web_cookie=''
                        elif body.get('revoke'):
                            web_login.revoke(store,actor,session_id=body['revoke'])
                        return self.respond(200,{'sessions':web_login.sessions(store,actor,web_token),
                                                 'browser':bool(web_token)})
                    if action=='assistant':
                        from .assistant import status
                        result=status(store,scoped)
                    elif action=='assistant-config':
                        from .assistant import configure
                        result=configure(store,scoped,body)
                    elif action=='food-count':
                        from .nutrition import count
                        result=count(str(body.get('text') or ''))
                    elif action in ('assistant-chat','assistant-ask','assistant-confirm','assistant-cancel','assistant-undo','assistant-forget'):
                        from . import assistant_web as chat
                        now=datetime.now(scoped.timezone)
                        if action=='assistant-chat':result=chat.chat(store,scoped)
                        elif action=='assistant-ask':result=chat.ask(store,scoped,Schedule(store,scoped),actor,body.get('text'),now)
                        elif action=='assistant-confirm':result=chat.confirm(store,actor,body.get('pending'),now)
                        elif action=='assistant-cancel':result=chat.cancel(store,actor,body.get('pending'),now)
                        elif action=='assistant-undo':result=chat.undo(store,actor,body.get('run'))
                        else:result=chat.forget(store)
                    elif action in ('billing','salary'):
                        from .reollity import billing_state
                        month=date.fromisoformat(body['month'][0]+'-01')
                        result=billing_state(store,Schedule(store,scoped),month)
                        if action=='salary':result=result['salary']
                    elif action=='wellness':
                        from .wellness import Wellness
                        day=date.fromisoformat(body['day'][0]) if body.get('day') else None
                        result=Wellness(store,scoped.timezone).overview(day)
                    elif action=='recipes':
                        from . import recipe_links, recipes
                        result=dict(recipes=recipes.catalog(),links=recipe_links.links(store))
                    elif action=='study':
                        from .study import overview
                        result=overview(store,scoped,Schedule(store,scoped),datetime.now(scoped.timezone))
                    elif action=='state':
                        first,last = date.fromisoformat(body['from'][0]),date.fromisoformat(body['to'][0])
                        if not 0<=(last-first).days<=41:
                            raise ValueError()
                        result = asyncio.run(request_app.state(store,first,last))
                    else:
                        result = request_app.mutate(store,action,body)
                    self.respond(200,result)
                except PermissionError as exc:
                    self.respond(403,{'error':str(exc)})
                except (ValueError,KeyError,TypeError,IndexError) as exc:
                    journal_action=action.startswith(('wellness-','workout-','assistant-','salary-','calendar-import'))
                    message=str(exc) if journal_action and isinstance(exc,ValueError) else 'Проверьте поля, дату и время.'
                    self.respond(400,{'error':message})
                except Exception:
                    # The person sees a short message; the log keeps the traceback (logsafe strips secrets).
                    log.exception('API %s failed',action)
                    self.respond(500,{'error':'Не удалось загрузить или сохранить. Повторите запрос.'})
                finally:
                    if store:
                        store.close()
        return Handler


def start_server(config, telegram=None):
    server = ThreadingHTTPServer((os.getenv('MINI_APP_HOST','127.0.0.1'),int(os.getenv('MINI_APP_PORT','8765'))),
                                 App(config,telegram).handler())
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server
