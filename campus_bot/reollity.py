"""Reollity reads only. Login is the ONLY allowed POST; no platform write endpoints exist here."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .models import at
from .tutoring import LessonBook, person_key, money

BASE = 'https://api.reollity.ru'
READ_PATH = re.compile(r'/students(?:/\d+/(?:lessons|transactions|balance)\?mine=1)?|/auth/me|/reports/salary\?year=\d{4}&month=(?:[1-9]|1[0-2])')


class ReollityError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReollityError('Reollity вернул перенаправление; запрос остановлен.')


def kopecks(value):
    number = Decimal(str(value))
    if not number.is_finite() or number*100 != (number*100).to_integral_value():
        raise ReollityError('Не удалось точно прочитать сумму Reollity')
    return int(number*100)


def local_day(value, tz):
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ReollityError('У операции отсутствует часовой пояс')
    return moment.astimezone(tz).date().isoformat()


class ReadOnlyClient:
    def __init__(self, username, password, tz, opener=None):
        self.username, self.password, self.tz = username, password, tz
        self.opener = opener or build_opener(NoRedirect())

    def request(self, method, path, token=None, body=None):
        if not ((method == 'GET' and READ_PATH.fullmatch(path) and body is None)
                or (method == 'POST' and path == '/auth/login' and token is None)):
            raise ReollityError('Разрешено только чтение Reollity и вход в аккаунт')
        headers = {'Content-Type': 'application/json', 'User-Agent': 'CampusDayBot/read-only'}
        if token:
            headers['Authorization'] = 'Bearer '+token
        request = Request(BASE+path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(8*1024*1024+1)
                if len(raw)>8*1024*1024:
                    raise ReollityError('Слишком большой ответ Reollity')
                return json.loads(raw)
        except HTTPError as exc:
            raise ReollityError(f'Reollity: HTTP {exc.code}. Данные бота сохранены.') from None
        except (URLError, OSError, ValueError):
            raise ReollityError('Не удалось прочитать Reollity. Сохранена предыдущая сверка.') from None

    def fetch(self, salary_months=None):
        auth = self.request('POST', '/auth/login', body={'username': self.username, 'password': self.password})
        token, teacher = auth['token'], int(auth['id'])
        students = self.request('GET', '/students', token)
        if not isinstance(students, list) or len(students)>500:
            raise ReollityError('Изменился формат списка учеников Reollity')
        def fetch_one(student):
            sid = int(student['id'])
            lessons = self.request('GET', f'/students/{sid}/lessons?mine=1', token)
            transactions = self.request('GET', f'/students/{sid}/transactions?mine=1', token)
            balance = self.request('GET', f'/students/{sid}/balance?mine=1', token)['balance']
            return normalize_account(student, lessons, transactions, balance, teacher, self.tz)
        with ThreadPoolExecutor(max_workers=4) as pool:
            accounts = list(pool.map(fetch_one, students))
        current=datetime.now(self.tz).date().replace(day=1)
        months=salary_months or [current.strftime('%Y-%m'),(current-timedelta(days=1)).strftime('%Y-%m')]
        reports, errors = {}, {}
        for month in dict.fromkeys(months):
            try:
                first=datetime.strptime(month,'%Y-%m').date()
                payload=self.request('GET',f'/reports/salary?year={first.year}&month={first.month}',token)
                reports[month]=normalize_salary(payload,month)
            except (ReollityError,ValueError,KeyError,TypeError):
                errors[month]='Не удалось прочитать зарплатный отчёт. Сохранён предыдущий расчёт.'
        return dict(teacher_id=teacher, accounts=accounts, salary_reports=reports, salary_errors=errors)


def normalize_salary(raw,month):
    """Read the platform's own payroll, including its late-report/transfer adjustments."""
    first=datetime.strptime(month,'%Y-%m').date()
    if type(raw.get('year')) is not int or type(raw.get('month')) is not int or (raw['year'],raw['month'])!=(first.year,first.month):
        raise ReollityError('Reollity вернул зарплату за другой месяц')
    result=dict(month=first.strftime('%Y-%m'))
    for field in ('total_all','late_reports_amount','income_counted','bank_transfer_deduction','salary','lessons_without_report_amount'):
        value=raw[field]
        if isinstance(value,bool):raise ReollityError('Некорректная сумма зарплатного отчёта')
        result[field]=kopecks(value)
    rows,prices=raw['report_breakdown'],raw['lessons_by_price']
    if not isinstance(rows,list) or not isinstance(prices,list) or len(rows)>1000 or len(prices)>1000:
        raise ReollityError('Неизвестный формат зарплатного отчёта')
    result['reports']=[]
    for row in rows:
        if type(row['is_late']) is not bool:raise ReollityError('Неизвестный признак опоздания отчёта')
        result['reports'].append(dict(id=int(row['report_id']),day=date.fromisoformat(row['report_date'][:10]).isoformat(),
                                     late=row['is_late'],amount=kopecks(row['amount'])))
    if len({r['id'] for r in result['reports']})!=len(result['reports']):raise ReollityError('Повторяющиеся зарплатные отчёты')
    result['prices']=[]
    for row in prices:
        count=row['lessons_count']
        if type(count) is not int or count<0:raise ReollityError('Неверное число занятий')
        result['prices'].append(dict(price=kopecks(row['price']),count=count))
    result['participations']=sum(p['count'] for p in result['prices'])
    return result


def normalize_account(student, lessons, transactions, balance, teacher, tz):
    """Drop phone, parent, email, free-form descriptions and all authentication fields."""
    sid = int(student['id'])
    if not isinstance(lessons, list) or not isinstance(transactions, list):
        raise ReollityError('Изменился формат истории Reollity')
    result = dict(platform_id=sid, name=str(student['name'])[:150], archived=bool(student.get('is_archived')),
                  balance=kopecks(balance), lessons=[], transactions=[])
    for row in lessons:
        if int(row['student_id'])!=sid or int(row['created_by'])!=teacher or row['status'] not in ('attended','missed','makeup'):
            raise ReollityError('Неизвестный преподаватель или статус занятия. Импорт остановлен.')
        duration = int(row['duration_minutes'])
        if not 5<=duration<=1440 or type(row['is_chargeable']) is not bool:
            raise ReollityError('Неизвестная длительность или признак оплаты занятия')
        result['lessons'].append(dict(id=int(row['id']), day=date.fromisoformat(row['lesson_date'][:10]).isoformat(),
            time=row['lesson_time'][:5], duration=duration, amount=kopecks(row['price']), status=row['status'],
            chargeable=row['is_chargeable']))
    known = {l['id']: l for l in result['lessons']}
    for row in transactions:
        kind = row['type']
        if kind not in ('lesson','deposit') or int(row['student_id'])!=sid:
            raise ReollityError('Неизвестный тип операции Reollity. Импорт остановлен.')
        amount = kopecks(row['amount'])
        if amount < 0:
            raise ReollityError('Неизвестное направление суммы Reollity')
        posted = local_day(row['created_at'],tz)
        lesson_id = int(row['lesson_id']) if row.get('lesson_id') is not None else None
        if kind == 'lesson' and lesson_id not in known:
            raise ReollityError('Для списания не найдено занятие. Сверка остановлена.')
        # Late-created reports belong to the lesson's actual date, not the posting date.
        day = known[lesson_id]['day'] if kind=='lesson' else posted
        result['transactions'].append(dict(id=int(row['id']), kind=kind, amount=amount,
            day=day, posted_day=posted, lesson_id=lesson_id, effect=amount if kind=='deposit' else -amount))
    if len({t['id'] for t in result['transactions']}) != len(result['transactions']):
        raise ReollityError('Повторяющиеся операции Reollity')
    if sum(t['effect'] for t in result['transactions']) != result['balance']:
        raise ReollityError('Баланс не совпал с историей операций. Сверка не заменяет данные.')
    return result


def apply_snapshot(store, schedule, snapshot, now):
    book = LessonBook(store,schedule)
    roster = book.roster()
    by_id = {s['id']:dict(s) for s in roster}
    aliases = store.get('reollity_name_links', {})  # Explicit owner-approved mappings only.
    accounts, grouped = [], {}
    mapped = set()
    for raw in snapshot['accounts']:
        account = dict(raw)
        parts = raw['name'].split()
        candidates = []
        for candidate in (raw['name'], ' '.join(reversed(parts))):
            try:
                uid = person_key(candidate)
                if uid in by_id:candidates.append(uid)
            except ValueError:
                pass
        explicit = aliases.get(str(raw['platform_id']))
        if explicit:
            uid = explicit
        elif len(set(candidates))==1:
            uid = candidates[0]
        elif len(set(candidates))>1:
            raise ReollityError('Неоднозначное совпадение имени ученика')
        else:
            uid = 'r'+str(raw['platform_id'])
        if uid in mapped:
            raise ReollityError('Две карточки платформы совпали с одним учеником')
        mapped.add(uid)
        pupil = by_id.get(uid, dict(id=uid,name=raw['name'],rates={}))
        pupil.update(name=raw['name'], platform_id=raw['platform_id'])
        by_id[uid] = pupil
        account['student_id'] = uid
        accounts.append(account)
        for lesson in raw['lessons']:
            if lesson['day']>=now.date().isoformat():
                continue  # The current and all future days are NEVER imported into the calendar.
            key = (lesson['day'], lesson['time'], lesson['duration'], lesson['status'], lesson['chargeable'])
            grouped.setdefault(key, []).append((uid, lesson))
    calendar_rows = []
    for (day,time,duration,status,chargeable), members in grouped.items():
        ids = [uid for uid,_ in members]
        if len(ids)!=len(set(ids)):
            raise ReollityError('Дубли занятий ученика в одном временном блоке')
        fingerprint = hashlib.sha256(json.dumps(sorted(l['id'] for _,l in members)).encode()).hexdigest()[:16]
        uid = 'personal:reollity-'+fingerprint
        start = at(date.fromisoformat(day), time, schedule.config.timezone)
        calendar_rows.append(dict(uid=uid, day=day, title='Занятие · '+' / '.join(by_id[i]['name'] for i in ids),
            start=start.isoformat(), end=(start+timedelta(minutes=duration)).isoformat(), students=ids,
            amounts={i:l['amount'] for i,l in members}, cancelled=status=='missed',
            status=status, details='Reollity · '+{'attended':'проведено','missed':'пропуск без списания','makeup':'отработка'}[status]))
    earliest = min([r['day'] for r in calendar_rows]+[(now.date().replace(day=1)-timedelta(days=1)).replace(day=1).isoformat()])
    meta = dict(fetched=now.isoformat(), first=earliest, cutoff=now.date().isoformat(),
                teacher_id=snapshot['teacher_id'], student_ids=sorted(mapped), pupils=len(accounts),
                lessons=sum(len(a['lessons']) for a in accounts), transactions=sum(len(a['transactions']) for a in accounts), error=None)
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        store.db.execute('DELETE FROM reollity_accounts')
        store.db.execute('DELETE FROM reollity_calendar')
        for pupil in by_id.values():
            store.db.execute('INSERT OR REPLACE INTO tutoring_students VALUES (?,?)', (pupil['id'],json.dumps(pupil,ensure_ascii=False)))
        for account in accounts:
            store.db.execute('INSERT INTO reollity_accounts VALUES (?,?)', (account['student_id'],json.dumps(account,ensure_ascii=False)))
        for row in calendar_rows:
            store.db.execute('INSERT INTO reollity_calendar VALUES (?,?,?)', (row['uid'],row['day'],json.dumps(row,ensure_ascii=False)))
            store.db.execute('INSERT OR REPLACE INTO checks VALUES (?,?)', (row['uid']+'|'+row['day'],int(not row['cancelled'])))
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('reollity_sync',json.dumps(meta,ensure_ascii=False)))
        salaries=store.get('reollity_salary_reports',{})
        for month,report in snapshot.get('salary_reports',{}).items():
            salaries[month]=dict(report,fetched=now.isoformat())
        salaries=dict(sorted(salaries.items())[-36:])
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('reollity_salary_reports',json.dumps(salaries,ensure_ascii=False)))
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('reollity_salary_errors',json.dumps(snapshot.get('salary_errors',{}),ensure_ascii=False)))
        pending=[month for month in store.get('salary_month_requests',[]) if month not in snapshot.get('salary_reports',{})]
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('salary_month_requests',json.dumps(pending)))
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('reollity_refresh_requested','false'))
    return meta


def statement(account, month):
    first = month.replace(day=1).isoformat()
    following = (month.replace(day=28)+timedelta(days=4)).replace(day=1).isoformat()
    tx = account['transactions']
    opening = account['balance']-sum(t['effect'] for t in tx if t['day']>=first)
    rows = [t for t in tx if first<=t['day']<following]
    payments = [t for t in rows if t['kind']=='deposit']
    charges = [t for t in rows if t['kind']=='lesson']
    total_paid = sum(t['amount'] for t in payments)
    cost = sum(t['amount'] for t in charges)
    return dict(month=first[:7], opening=opening, closing=opening+total_paid-cost,
                payments=payments, paid=total_paid, cost=cost, count=len(charges))


def payment_allocation(account, month, total):
    """Infer coverage oldest-first; deposits in Reollity have no link to a lesson."""
    first = month.replace(day=1)
    previous = (first-timedelta(days=1)).replace(day=1)
    following = (first.replace(day=28)+timedelta(days=4)).replace(day=1)
    available = sum(t['amount'] for t in account['transactions']
                    if t['kind']=='deposit' and t['day']<following.isoformat())
    lessons = {l['id']:l for l in account['lessons']}
    charges = sorted((t for t in account['transactions'] if t['kind']=='lesson' and t['day']<first.isoformat()),
                     key=lambda t:(t['day'],lessons.get(t['lesson_id'],{}).get('time',''),t['id']))
    rows, older_due = [], 0
    for charge in charges:
        paid = min(available,charge['amount'])
        available -= paid
        remaining = charge['amount']-paid
        if charge['day']<previous.isoformat():
            older_due += remaining
        else:
            rows.append(dict(day=charge['day'],time=lessons.get(charge['lesson_id'],{}).get('time',''),
                             amount=charge['amount'],paid=paid,remaining=remaining,
                             status='paid' if remaining==0 else 'partial' if paid else 'unpaid'))
    return dict(previous_dates=rows,previous_due=sum(r['remaining'] for r in rows),older_due=older_due,
                current_due=None if total is None else max(0,total-available),
                current_paid=None if total is None else min(available,total),
                leftover=None if total is None else max(0,available-total),method='oldest_first')


def bill(store, schedule, student, month, book=None, account_map=None):
    book = book or LessonBook(store,schedule)
    report = book.report(month,student)
    accounts = account_map if account_map is not None else {a['student_id']:a for a in store.platform_accounts()}
    account = accounts.get(student['id'])
    previous = (month.replace(day=1)-timedelta(days=1)).replace(day=1)
    from .income import share_of
    result = dict(id=student['id'], name=student['name'], rate=report['rate'], count=report['count'],
        share=share_of(store, student), own_rate=student.get('rate'), own_share=student.get('share'),
        total=report['total'], month=month.strftime('%Y-%m'), linked=bool(account),
        dates=[dict(day=e.start.strftime('%Y-%m-%d'),time=e.time_label,amount=amount,uid=e.uid,start=e.start.isoformat(),end=e.end.isoformat(),
                    done=store.checked(e.uid+'|'+e.start.date().isoformat())) for e,amount in zip(report['entries'],report['amounts'])])
    if account:
        prev, current = statement(account,previous), statement(account,month)
        result.update(previous=prev,current=current,balance=account['balance'],
            debt=max(0,-current['opening']), credit=max(0,current['opening']),
            due=None if report['total'] is None else max(0,report['total']-current['opening']-current['paid']),
            leftover=None if report['total'] is None else max(0,current['opening']+current['paid']-report['total']))
        result['settlement']=payment_allocation(account,month,report['total'])
    else:
        result.update(previous=None,current=None,balance=None,debt=None,credit=None,due=None,leftover=None,settlement=None)
    return result


def billing_state(store,schedule,month,now=None):
    month = month.replace(day=1)
    book=LessonBook(store,schedule)
    book.prepare_month(month)
    account_map={a['student_id']:a for a in store.platform_accounts()}
    rows = [bill(store,schedule,s,month,book=book,account_map=account_map) for s in book.roster()]
    rows.sort(key=lambda r:(-(r['due'] or 0),r['name'].casefold()))
    meta = store.get('reollity_sync', {})
    from .income import DEFAULT_SHARE, income
    from .salary import summary as salary_summary
    now = now or datetime.now(schedule.config.timezone)
    return dict(month=month.strftime('%Y-%m'), students=rows, sync=meta,
                salary=salary_summary(store, rows, month.strftime('%Y-%m'), now),
                refresh_requested=store.get('reollity_refresh_requested',False),
                total_due=sum(r['due'] or 0 for r in rows), unknown=sum(r['due'] is None for r in rows),
                income=income(rows, month.strftime('%Y-%m')),
                defaults=dict(rate=store.get('tutoring_default_rate'), share=store.get('tutoring_share', DEFAULT_SHARE)))


def bill_details_text(row, meta):
    lines = [f'👤 {row["name"]}\n💳 ОПЛАТА · {row["month"][5:7]}.{row["month"][:4]}']
    prev, current = row['previous'],row['current']
    if prev:
        lines += [f'ПРОШЛЫЙ МЕСЯЦ · {prev["month"][5:7]}.{prev["month"][:4]}\n'
                  f'Проведено и списано: {prev["count"]} зан. · {money(prev["cost"])}\n'
                  f'Поступило: {len(prev["payments"])} оплат · {money(prev["paid"])}',
                  f'Долг к началу месяца: {money(row["debt"])}\nАванс к началу месяца: {money(row["credit"])}']
    lines.append('ТЕКУЩИЙ ПЛАН\n'+f'{row["count"]} зан. за месяц · '+(money(row['total']) if row['total'] is not None else 'цена не задана'))
    if current:
        lines.append(f'Уже внесено за этот месяц: {money(current["paid"])}\n'+
                     (f'К ВНЕСЕНИЮ → {money(row["due"])}' if row['due'] is not None else 'Укажите цену для расчёта.'))
        if row['leftover']:
            lines.append('После покрытия месяца останется аванс: '+money(row['leftover']))
        lines.append('Расчёт: занятия месяца + старый долг − старый аванс − поступления месяца.')
    else:
        lines.append('Сверка оплат отсутствует: итог к внесению пока неизвестен.')
    if meta.get('fetched'):
        lines.append('Сверено Reollity: '+datetime.fromisoformat(meta['fetched']).strftime('%d.%m.%Y %H:%M')+' МСК.')
    if meta.get('error'):
        lines.append('⚠️ '+meta['error'])
    lines.append('Будущие занятия — прогноз вашего календаря. Изменения и оплаты отражаются после обновления сверки.')
    return '\n\n'.join(lines)


def date_labels(rows):
    from collections import Counter
    counts=Counter(r['day'] for r in rows)
    return [date.fromisoformat(r['day']).strftime('%d.%m')+
            (' '+r['time'] if counts[r['day']]>1 and r.get('time') else '') for r in rows]


def bill_text(row, meta):
    """The default chat card; bookkeeping detail lives behind a separate button."""
    from .tutoring import MONTHS
    month=date.fromisoformat(row['month']+'-01')
    previous=(month-timedelta(days=1)).replace(day=1)
    previous_label=MONTHS[previous.month-1]
    current_label=MONTHS[month.month-1]
    lines=[f'👤 {row["name"]} · {current_label.lower()} {month.year}']
    allocation=row.get('settlement')
    if allocation:
        old=allocation['previous_dates']
        section=[f'🗓 {previous_label} · {len(old)} зан.']
        labels=date_labels(old)
        for status,icon in (('paid','✅'),('partial','◐'),('unpaid','❌')):
            values=[label+(f' (ост. {money(r["remaining"])})' if status=='partial' else '')
                    for r,label in zip(old,labels) if r['status']==status]
            if values:section.append(icon+' '+', '.join(values))
        if not old:section.append('Занятий нет')
        section.append('Долг: '+money(allocation['previous_due']))
        if allocation['older_due']:section.append('Долг более ранних месяцев: '+money(allocation['older_due']))
        lines.append('\n'.join(section))
    else:
        lines.append(f'🗓 {previous_label} · нет сверки оплат')
    section=[f'📅 {current_label} · {row["count"]} зан. · '+(money(row['total']) if row['total'] is not None else 'цена не задана')]
    section.append(', '.join(date_labels(row['dates'])) or 'Занятий нет')
    if allocation:
        section.append('Осталось за месяц: '+(money(allocation['current_due']) if allocation['current_due'] is not None else 'укажите цену'))
    lines.append('\n'.join(section))
    lines.append('💳 ИТОГО К ОПЛАТЕ: '+(money(row['due']) if row['due'] is not None else 'нет полного расчёта'))
    if row.get('leftover'):lines.append('Аванс после оплаты месяца: '+money(row['leftover']))
    if allocation and allocation['previous_dates']:
        lines.append('✅ оплачено · ◐ частично · ❌ не оплачено\nОплаты — по порядку дат.')
    if meta.get('error'):lines.append('⚠️ Показана последняя успешная сверка.')
    return '\n\n'.join(lines)


class ReollitySync:
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.retry_at = None

    @property
    def configured(self):
        return not self.bot.config.public_mode and bool(os.getenv('REOLLITY_USER') and os.getenv('REOLLITY_PASSWORD'))

    async def refresh(self, now=None, force=False):
        now = now or self.bot.now()
        if not self.configured:
            return None
        if self.lock.locked():
            return None
        async with self.lock:
            meta = self.bot.store.get('reollity_sync', {})
            requested = self.bot.store.get('reollity_refresh_requested',False)
            if not (force or requested) and meta.get('fetched') and now-datetime.fromisoformat(meta['fetched'])<timedelta(hours=1):
                return meta
            if self.retry_at and now<self.retry_at and not force:
                return None
            try:
                client = ReadOnlyClient(os.environ['REOLLITY_USER'],os.environ['REOLLITY_PASSWORD'],self.bot.config.timezone)
                months=[now.strftime('%Y-%m'),(now.date().replace(day=1)-timedelta(days=1)).strftime('%Y-%m')]
                months+=self.bot.store.get('salary_month_requests',[])[:4]
                snapshot = await asyncio.to_thread(client.fetch,months)
                meta = apply_snapshot(self.bot.store,self.bot.schedule,snapshot,now)
                self.retry_at = None
                return meta
            except (ReollityError,KeyError,ValueError,TypeError):
                meta['error'] = 'Не удалось сверить Reollity. Показана предыдущая успешная сверка.'
                self.bot.store.set('reollity_sync',meta)
                self.retry_at = now+timedelta(minutes=15)
                return None
