"""Private pupil register, calendar-based monthly totals and one-occurrence transfers."""
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import uuid4

from .models import at, clock, parse_day, overlaps

MONTHS = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')
DATE = r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}(?:\.\d{4})?)'
REQUEST = re.compile(rf'^(?:\d+[).]\s*)?({DATE})(?:\s+(\d{{1,2}}:\d{{2}}))?\s*[-–—]\s*(.+?)(?:\s+вместо\s+({DATE}))?\s*$', re.I)


def event_key(event):
    return event.uid+'|'+event.start.date().isoformat()


def person_key(name):
    words = re.findall(r'[A-Za-zА-Яа-яЁё-]+', name)
    if len(words) < 2:
        raise ValueError('Укажите фамилию и имя ученика')
    raw = words[0].casefold().replace('ё', 'е')+' '+words[1][0].casefold().replace('ё', 'е')
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def people(title):
    if '·' in title:
        title = title.split('·', 1)[1].strip()
    elif '/' not in title:
        return []
    parts = [p.strip() for p in title.split('/')]
    # Do not mistake generic lesson titles or lectures for pupils.
    pattern = r'[A-ZА-ЯЁ][a-zа-яё-]+\s+(?:[A-ZА-ЯЁ]\.?|[A-ZА-ЯЁ][a-zа-яё-]+)(?:\s+[A-ZА-ЯЁ][a-zа-яё-]+)?'
    return parts if all(re.fullmatch(pattern, p) for p in parts) else []


def month_start(value, today):
    if not value:
        return today.replace(day=1)
    if re.fullmatch(r'\d{1,2}\.\d{4}', value):
        month, year = map(int, value.split('.'))
        return date(year, month, 1)
    if re.fullmatch(r'\d{4}-\d{2}', value):
        return date.fromisoformat(value+'-01')
    return parse_day(value, today).replace(day=1)


def money(kopecks):
    value = Decimal(kopecks)/100
    return f'{value:,.2f}'.replace(',', ' ').removesuffix('.00').replace('.', ',')+' ₽'


def price(value):
    try:
        amount = Decimal(value.strip().lower().replace('руб.', '').replace('руб', '').replace('₽', '').replace(' ', '').replace(',', '.'))
        if not amount.is_finite() or amount < 0 or amount > 1000000 or amount*100 != (amount*100).to_integral_value():
            raise ValueError()
        return int(amount*100)
    except (InvalidOperation, AttributeError):
        raise ValueError('Введите цену занятия в рублях, например 1800') from None


def name_words(value):
    return re.findall(r'[a-zа-я]+',value.casefold().replace('ё','е'))


def matches_name(query, words):
    if not query:return True
    return any(word.startswith(query[0]) and matches_name(query[1:],words[:i]+words[i+1:])
               for i,word in enumerate(words))


class LessonBook:
    def __init__(self, store, schedule):
        self.store, self.schedule = store, schedule
        self._month_snapshot = None

    def roster(self):
        known = {s['id']: s for s in self.store.students()}
        for rule in self.store.rules():
            if rule.get('student_ids') and all(uid in known for uid in rule['student_ids']):
                continue
            for name in people(rule['title']):
                uid = person_key(name)
                if uid not in known:
                    known[uid] = dict(id=uid, name=name, rates={})
                    self.store.put_student(known[uid])
        return sorted(known.values(), key=lambda s: s['name'].casefold())

    def resolve(self, value):
        students = self.roster()
        result = []
        for name in value.split('/'):
            name = name.strip()
            uid = person_key(name)
            exact = next((s for s in students if s['name'].casefold()==name.casefold()),None)
            if exact:uid=exact['id']
            matches = [s for s in students if s['id'] == uid]
            if not matches:
                if not re.fullmatch(r'[А-ЯЁA-Z][а-яёa-z-]+\s+[А-ЯЁA-Z][а-яёa-z-]+', name):
                    raise ValueError('Новый ученик: укажите полные фамилию и имя')
                student = dict(id=uid, name=name, rates={})
                self.store.put_student(student)
                students.append(student)
            else:
                student = matches[0]
                # Expand the existing initial instead of creating a second pupil.
                if not student.get('platform_id') and len(re.findall(r'[А-Яа-яЁёA-Za-z-]+', name)[1]) > 1:
                    existing = re.findall(r'[А-Яа-яЁёA-Za-z-]+', student['name'])[1]
                    if len(existing) > 1 and existing.casefold() != name.split()[1].casefold():
                        raise ValueError('Совпали фамилия и инициал разных имён. Уточните ученика в расписании.')
                    student = dict(student, name=name)
                    self.store.put_student(student)
            if student['id'] in result:
                raise ValueError('Ученик указан дважды')
            result.append(student['id'])
        if not 1 <= len(result) <= 8:
            raise ValueError('От одного до восьми учеников за занятие')
        return sorted(result)

    def find(self, query):
        students=self.roster()
        names={s['id']:[s['name']] for s in students}
        for rule in self.store.rules():
            for alias in people(rule['title']):
                uid=person_key(alias)
                if uid in names:names[uid].append(alias)
        words=sorted(name_words(query),key=len,reverse=True)
        return [s for s in students if words and any(matches_name(words,name_words(n)) for n in names[s['id']])]

    def names(self, ids):
        students = {s['id']: s for s in self.roster()}
        return ' / '.join(students[uid]['name'] for uid in ids)

    def ids(self, event, rules=None):
        imported = self.store.platform_event(event.uid)
        if imported:
            return sorted(imported['students'])
        rule = (rules or {('personal:'+r['id']):r for r in self.store.rules()}).get(event.uid,{})
        if rule.get('student_ids'):
            return sorted(rule['student_ids'])
        return sorted({person_key(n) for n in (people(event.title) or people(rule.get('title', '')))})

    def entries(self, first, last, student=None, cancelled=False):
        cached=self._month_snapshot
        if cached and cached['first']==first and cached['last']==last and not cancelled:
            return [e for e in cached['events'] if not student or student in cached['students'][event_key(e)]]
        self.roster()
        rules=self.store.rules()
        by_id={'personal:'+r['id']:r for r in rules}
        rows = []
        day = first
        while day <= last:
            for event in self.schedule.personal(day,rules=rules):
                ids = self.ids(event,by_id)
                if ids and (cancelled or not event.cancelled) and (not student or student in ids):
                    rows.append(event)
            day += timedelta(days=1)
        return rows

    def prepare_month(self, month):
        """Request-local only: compute one calendar shared by all pupil reports."""
        first=month.replace(day=1)
        last=first.replace(day=calendar.monthrange(first.year,first.month)[1])
        self._month_snapshot=None
        events=self.entries(first,last)
        by_id={'personal:'+r['id']:r for r in self.store.rules()}
        self._month_snapshot=dict(first=first,last=last,events=events,
                                  students={event_key(e):self.ids(e,by_id) for e in events})

    def rate(self, student, month):
        return student.get('rates', {}).get(month.strftime('%Y-%m'),
               student.get('rate', self.store.get('tutoring_default_rate')))

    def report(self, month, student):
        first = month.replace(day=1)
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        entries = self.entries(first, last, student['id'])
        done = sum(self.store.checked(event_key(e)) for e in entries)
        rate = self.rate(student, first)
        amounts = []
        for event in entries:
            imported = self.store.platform_event(event.uid)
            amounts.append(imported['amounts'].get(student['id']) if imported else rate)
        total = None if any(v is None for v in amounts) else sum(amounts)
        closed = [v for e,v in zip(entries,amounts) if self.store.checked(event_key(e))]
        earned = None if any(v is None for v in closed) else sum(closed)
        anchor = date.fromisoformat(self.store.get('cycle_anchor', self.schedule.anchor.isoformat()))
        coverage_note = (f'⚠️ Регулярное расписание начинается {anchor:%d.%m.%Y}. '
                         'За более ранние даты данные неполные.') if first < anchor and not self.store.get('reollity_sync') else ''
        return dict(first=first, last=last, entries=entries, count=len(entries), done=done, rate=rate,
                    amounts=amounts,
                    coverage_note=coverage_note,
                    total=total, earned=earned)

    def summary(self, month):
        book=LessonBook(self.store,self.schedule)
        book.prepare_month(month)
        lines = [f'💰 ЗАНЯТИЯ · {MONTHS[month.month-1].upper()} {month.year}',
                 'По расписанию за весь месяц; отмены исключены.\nКаждый ученик пары учитывается отдельно.']
        total, confirmed, unknown = 0, 0, False
        anchor = date.fromisoformat(self.store.get('cycle_anchor', self.schedule.anchor.isoformat()))
        if month.replace(day=1) < anchor and not self.store.get('reollity_sync'):
            lines.append(f'⚠️ Регулярное расписание начинается {anchor:%d.%m.%Y}; более ранняя история неполная.')
        for student in book.roster():
            report = book.report(month, student)
            if not report['count']:
                continue
            amount = money(report['total']) if report['total'] is not None else 'цена не задана'
            lines.append(f'{student["name"]}: {report["count"]} зан. · {amount} · ✅ {report["done"]}')
            total += report['total'] or 0
            confirmed += report['earned'] or 0
            unknown |= report['total'] is None
        lines.append(('Итого с указанными ценами' if unknown else 'Итого по расписанию')+': '+money(total))
        lines.append('✅ Подтверждено проведено: '+money(confirmed))
        lines.append('Это стоимость занятий, а не отметка об оплате.\nВыберите ученика через /students — даты, галочки и цена.')
        return '\n\n'.join(lines)

    def save(self, draft):
        """One transaction: no state where only one half of a transfer has been applied."""
        self.roster()  # Seed names before opening the transaction (put_student commits).
        source = None
        with self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            existing = next((c for c in self.store.lesson_changes() if c['id'] == draft['id']), None)
            if existing:
                if not existing['active']:
                    raise ValueError('Изменение уже отменено. Пришлите запрос заново.')
                return existing, False
            ids = sorted(draft['students'])
            target_day = date.fromisoformat(draft['day'])
            start = at(target_day, clock(draft['time']), self.schedule.config.timezone)
            duration = int(draft['duration'])
            if not 5 <= duration <= 1440:
                raise ValueError('Длительность от 5 до 1440 минут')
            if draft.get('source_key'):
                source_day = date.fromisoformat(draft['source_key'].rsplit('|', 1)[1])
                source = next((e for e in self.entries(source_day, source_day) if event_key(e) == draft['source_key'] and self.ids(e) == ids), None)
                if not source or self.snapshot(source) != draft['source']:
                    raise ValueError('Исходное занятие изменилось или уже перенесено. Пришлите запрос заново.')
                if self.store.checked(event_key(source)):
                    raise ValueError('Занятие отмечено проведённым. Сначала снимите галочку, затем переносите.')
                if source.start == start:
                    raise ValueError('Исходная и новая дата со временем совпадают')
            same = [e for e in self.entries(target_day, target_day) if e.start == start and self.ids(e) == ids]
            if same:
                raise ValueError('На эту дату и время такое занятие уже есть. Дубликат не добавлен.')
            rule = dict(id='lesson-'+draft['id'], title='Занятие · '+self.names(ids), cycle='once', date=str(target_day),
                        weekdays=[], time=clock(draft['time']), duration_minutes=duration, student_ids=ids,
                        note=('Перенос с '+source.start.strftime('%d.%m.%Y %H:%M')) if source else 'Добавлено в чате')
            change = dict(id=draft['id'], active=True, rule=rule, source_key=event_key(source) if source else None,
                          created=draft['created'])
            # These writes deliberately share the outer transaction.
            self.store.db.execute('INSERT INTO rules VALUES (?,?)', (rule['id'], json.dumps(rule, ensure_ascii=False)))
            self.store.db.execute('INSERT INTO lesson_changes VALUES (?,?)', (change['id'], json.dumps(change, ensure_ascii=False)))
        return change, True

    @staticmethod
    def snapshot(event):
        return [event.uid, event.title, event.start.isoformat(), event.end.isoformat()]

    def undo(self, uid):
        with self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            change = next((c for c in self.store.lesson_changes() if c['id'] == uid and c['active']), None)
            if not change:
                return False
            rule = change['rule']
            current = next((r for r in self.store.rules() if r['id'] == rule['id']), None)
            key = 'personal:'+rule['id']+'|'+rule['date']
            if current != rule or self.store.override(key) or self.store.checked(key) or any(
                    c.get('active') and c.get('source_key') == key for c in self.store.lesson_changes()):
                raise ValueError('Занятие после добавления меняли, отметили или переносили. Сначала отмените последнюю правку.')
            self.store.db.execute('DELETE FROM rules WHERE id=?', (rule['id'],))
            change['active'] = False
            self.store.db.execute('UPDATE lesson_changes SET value=? WHERE id=?', (json.dumps(change, ensure_ascii=False), uid))
        return True


def btn(text, action):
    return dict(text=text, callback_data='tu:'+action)


def markup(*rows):
    return dict(inline_keyboard=list(rows))


class Tutoring:
    def __init__(self, bot):
        self.bot, self.store = bot, bot.store
        self.book = LessonBook(bot.store, bot.schedule)

    def state(self):
        state = self.store.get('tutoring_pending')
        if state and datetime.fromisoformat(state['expires']) < self.bot.now():
            self.store.set('tutoring_pending', None)
            return None
        return state

    def pending(self, **values):
        state = dict(values, id=uuid4().hex[:12], created=self.bot.now().isoformat(),
                     expires=(self.bot.now()+timedelta(minutes=30)).isoformat())
        self.store.set('tutoring_pending', state)
        self.store.set('chat_pending', None)
        return state

    async def students(self, month=None, page=0, message=None):
        month = (month or self.bot.now().date()).replace(day=1)
        students = self.book.roster()
        page = max(0, min(page, max(0, (len(students)-1)//8)))
        rows = [[btn(s['name'], f'student:{s["id"]}:{month}')] for s in students[page*8:page*8+8]]
        if len(students)>8:
            rows.append([btn('‹ Ученики', f'list:{month}:{max(0,page-1)}'), btn('Ученики ›', f'list:{month}:{page+1}')])
        rows += [[btn('‹ Месяц', f'list:{month-timedelta(days=1)}:0'),
                  btn('Месяц ›', f'list:{month+timedelta(days=32)}:0')],
                 [btn('💰 Все ученики', f'all:{month}'), btn('✍️ Как добавить', 'help')],
                 [btn('🔔 Автоотчёт: '+('вкл' if self.store.get('tutoring_monthly_report', True) else 'выкл'), f'auto:{month}')]]
        if self.store.get('reollity_sync') or self.bot.reollity.configured:
            rows.append([btn('↻ Сверить Reollity', f'sync:{month}')])
        await self.bot.chat.screen(f'👥 УЧЕНИКИ · {MONTHS[month.month-1].upper()} {month.year}\n\n'
            'Выберите ученика: все даты с начала до конца месяца, количество и сумма.\n'
            'Можно выбрать другой месяц: /students 11.2026\n'
            'Автоотчёт: 1-го числа в 10:00 — предоплата на месяц и остаток прошлого (МСК).', markup(*rows), message)

    async def student(self, uid, month, page=0, message=None):
        from .reollity import bill,bill_text
        month=month.replace(day=1)
        student=next(s for s in self.book.roster() if s['id']==uid)
        row=bill(self.store,self.bot.schedule,student,month)
        today=self.bot.now().date().replace(day=1)
        rows=[[btn('‹ Месяц',f'student:{uid}:{month-timedelta(days=1)}'),
               btn('Сейчас',f'student:{uid}:{today}'),btn('Месяц ›',f'student:{uid}:{month+timedelta(days=32)}')],
              [btn('🧾 Платежи',f'payments:{uid}:{month}'),btn('📅 Занятия',f'lessons:{uid}:{month}:0')],
              [btn('↻ Обновить',f'sync:{month}:{uid}'),btn('⋯ Подробнее',f'details:{uid}:{month}')]]
        await self.bot.chat.screen(bill_text(row,self.store.get('reollity_sync',{})),markup(*rows),message)

    async def details(self, uid, month, message=None):
        from .reollity import bill,bill_details_text
        student=next(s for s in self.book.roster() if s['id']==uid)
        row=bill(self.store,self.bot.schedule,student,month)
        await self.bot.chat.screen(bill_details_text(row,self.store.get('reollity_sync',{})),markup(
            [btn('✎ Цена на месяц',f'rate:{uid}:{month}'),btn('👥 Другой ученик',f'list:{month}:0')],
            [btn('‹ Краткая карточка',f'student:{uid}:{month}')]),message)

    async def lesson_details(self, uid, month, page=0, message=None):
        student = next(s for s in self.book.roster() if s['id'] == uid)
        r = self.book.report(month, student)
        page = max(0, min(page, max(0, (r['count']-1)//12)))
        lines = [f'📅 {student["name"]}\n{MONTHS[month.month-1]} {month.year} · {r["count"]} занятий']
        if r['coverage_note']:
            lines.append(r['coverage_note'])
        rows = []
        for e in r['entries'][page*12:page*12+12]:
            done = self.store.checked(event_key(e))
            label = ('✅ ' if done else '▫️ ')+e.start.strftime('%d.%m')+' · '+e.time_label
            lines.append(label)
            digest = hashlib.sha256(event_key(e).encode()).hexdigest()[:12]
            rows.append([btn(label, f'check:{uid}:{month}:{digest}:{page}')])
        if not r['count']:
            lines.append('Занятий в этом месяце нет.')
        lines.append('Нажмите дату: ✅ проведено · ▫️ без отметки.')
        if r['count']>12:
            lines.append(f'Страница {page+1}/{(r["count"]+11)//12}')
            rows.append([btn('‹ Даты', f'lessons:{uid}:{month}:{max(0,page-1)}'), btn('Даты ›', f'lessons:{uid}:{month}:{page+1}')])
        rows.append([btn('‹ К оплате',f'student:{uid}:{month}')])
        await self.bot.chat.screen('\n\n'.join(lines), markup(*rows), message)

    async def lookup(self, text, explicit=False):
        text=text.strip()
        prefix=re.match(r'^(?:оплата|оплату|долг|ученик|ученица)\s*[:—-]?\s+(.+)$',text,re.I)
        if prefix:text=prefix[1];explicit=True
        month=self.bot.now().date().replace(day=1)
        dated=re.fullmatch(r'(.+?)\s+(\d{1,2}\.\d{4}|\d{4}-\d{2})',text)
        if dated:
            try:month=month_start(dated[2],self.bot.now().date())
            except ValueError:
                await self.bot.reply('Укажите месяц как 11.2026 или 2026-11.');return True
            text=dated[1].strip()
        if not re.fullmatch(r'[А-Яа-яЁёA-Za-z.\s-]{2,150}',text) or len(name_words(text))>5:
            if explicit:await self.bot.reply('Напишите имя или фамилию ученика. Например: /pay Иванов.')
            return explicit
        matches=self.book.find(text)
        if not matches:
            if explicit:await self.bot.reply('Ученика не нашёл. /students — список учеников.')
            return explicit
        if len(matches)==1:
            await self.student(matches[0]['id'],month)
        else:
            state=dict(nonce=uuid4().hex[:8],month=str(month),ids=[s['id'] for s in matches],
                       expires=(self.bot.now()+timedelta(minutes=30)).isoformat())
            self.store.set('tutoring_search',state)
            await self.search_choices(state)
        return True

    async def search_choices(self, state, page=0, message=None):
        names={s['id']:s['name'] for s in self.book.roster()}
        ids=[uid for uid in state['ids'] if uid in names]
        page=max(0,min(page,max(0,(len(ids)-1)//8)))
        rows=[[btn(names[uid],f'student:{uid}:{state["month"]}')] for uid in ids[page*8:page*8+8]]
        if len(ids)>8:
            rows.append([btn('‹',f'find:{state["nonce"]}:{max(0,page-1)}'),btn('›',f'find:{state["nonce"]}:{page+1}')])
        await self.bot.chat.screen('👥 Нашёл нескольких учеников. Выберите нужного.',markup(*rows),message)

    async def request(self, text):
        match = REQUEST.fullmatch(text)
        if not match:
            return False
        try:
            day, time, names, source_day = match.groups()
            day = parse_day(day, self.bot.now().date())
            ids = self.book.resolve(names)
            state = self.pending(step='source' if source_day else 'time', day=str(day), students=ids,
                                 time=clock(time) if time else None, duration=120)
            if source_day:
                source_day = parse_day(source_day, self.bot.now().date())
                entries = [e for e in self.book.entries(source_day, source_day) if self.book.ids(e) == ids]
                if not entries:
                    self.store.set('tutoring_pending', None)
                    await self.bot.reply('На исходную дату нет активного занятия с этим составом учеников. Ничего не изменено. '
                                         'Для переноса пары укажите обоих учеников через /.')
                elif len(entries) == 1:
                    await self.source(state, entries[0])
                else:
                    state['sources'] = [self.book.snapshot(e) for e in entries]
                    self.store.set('tutoring_pending', state)
                    await self.bot.reply('Какое именно занятие перенести?', reply_markup=markup(
                        *[[btn(e.time_label+' · '+e.title[:45], f'source:{state["id"]}:{i}')] for i,e in enumerate(entries)],
                        [btn('Отмена', 'cancel:'+state['id'])]))
            elif state['time']:
                await self.save(state)
            else:
                same = [e for e in self.book.entries(day, day) if self.book.ids(e) == ids]
                if same:
                    await self.bot.reply('На этот день уже есть занятие: '+', '.join(e.time_label for e in same)+
                        '.\nЕсли нужно ещё одно, напишите его время (например 12:00). /cancel — отменить.')
                else:
                    times = sorted({r['time'] for r in self.store.rules()
                                    if sorted(r.get('student_ids') or [person_key(n) for n in people(r['title'])]) == ids})
                    if len(times) == 1:
                        state['time'] = times[0]
                        durations = {r['duration_minutes'] for r in self.store.rules()
                                     if sorted(r.get('student_ids') or [person_key(n) for n in people(r['title'])]) == ids}
                        if len(durations) == 1:
                            state['duration'] = durations.pop()
                        await self.save(state)
                    else:
                        await self.bot.reply(f'📚 {self.book.names(ids)}\n{day:%d.%m.%Y}\n\n'
                            'Во сколько добавить? Выберите время или напишите ЧЧ:ММ.\n'
                            'Длительность по умолчанию — 120 минут; можно ввести «12:00 90».', reply_markup=markup(
                            *[[btn(t, f'time:{state["id"]}:{t}')] for t in times[:8]],
                            [btn('Отмена', 'cancel:'+state['id'])]))
        except (ValueError, KeyError) as exc:
            await self.bot.reply('Не удалось добавить занятие: '+str(exc))
        return True

    async def source(self, state, event):
        state.update(source_key=event_key(event), source=self.book.snapshot(event), step='time',
                     time=state['time'] or event.start.strftime('%H:%M'),
                     duration=int((event.end-event.start).total_seconds()/60))
        self.store.set('tutoring_pending', state)
        await self.save(state)

    async def save(self, state):
        try:
            change, created = self.book.save(state)
        except ValueError as exc:
            await self.bot.reply(str(exc)+'\n/cancel — отменить ввод.')
            return
        self.store.set('tutoring_pending', None)
        rule = change['rule']
        day = date.fromisoformat(rule['date'])
        label = 'ПЕРЕНЕСЕНО' if change['source_key'] else 'ДОБАВЛЕНО ОДИН РАЗ'
        event = next(e for e in self.bot.schedule.personal(day) if e.uid == 'personal:'+rule['id'])
        lines = [f'✅ {label}\n\n{self.book.names(rule["student_ids"])}\n{day:%d.%m.%Y} · {event.time_label}']
        if change['source_key']:
            original = date.fromisoformat(change['source_key'].rsplit('|',1)[1])
            lines.append(f'С {original:%d.%m.%Y} убрано только это занятие. Остальные недели сохранены.')
        # Personal conflicts can be checked without an unreliable university request.
        if any(event in pair for pair in overlaps(self.bot.schedule.personal(day))):
            lines.append('⚠️ Есть пересечение с другим личным занятием. Проверьте расписание дня.')
        lines.append('Месячные количество и сумма пересчитаны. Проведение отмечается галочкой отдельно.')
        await self.bot.reply('\n\n'.join(lines), reply_markup=markup(
            [btn('💰 Ученики за месяц', f'list:{day.replace(day=1)}:0'), btn('↩ Отменить изменение', 'undo:'+change['id'])],
            [dict(text='📅 Этот день', callback_data='c:day:'+str(day))]))

    async def input(self, text):
        state = self.state()
        if not state:
            return False
        try:
            if state['step'] == 'rate':
                student = next(s for s in self.book.roster() if s['id'] == state['student'])
                student.setdefault('rates', {})[state['month'][:7]] = price(text)
                self.store.put_student(student)
                self.store.set('tutoring_pending', None)
                await self.student(student['id'], date.fromisoformat(state['month']))
            elif state['step'] == 'time':
                parts = text.split()
                state['time'] = clock(parts[0])
                state['duration'] = int(parts[1]) if len(parts)>1 else state['duration']
                await self.save(state)
            else:
                await self.bot.reply('Выберите исходное занятие кнопкой или /cancel.')
        except (ValueError, KeyError, StopIteration):
            await self.bot.reply('Проверьте ответ: цена в рублях или время «12:00» / «12:00 90». /cancel — отменить.')
        return True

    async def help(self):
        await self.bot.reply('📚 ЗАНЯТИЯ В ЧАТЕ\n\n'
            '05.11 — Фамилия Имя/Фамилия Имя\nДобавить один раз; если обычных времён несколько — предложу выбрать.\n\n'
            '05.11 12:00 — Фамилия Имя/Фамилия Имя\nДобавить один раз в указанное время.\n\n'
            '05.11 — Фамилия Имя/Фамилия Имя вместо 10.11\nПеренести с 10-го на 5-е, с прежними временем и длительностью.\n'
            'Можно переносить вперёд и назад, в другой месяц. Год: 05.01.2027.\n'
            'Чтобы изменить время при переносе: 05.11 12:00 — … вместо 10.11.\n\n'
            '/students — выбрать ученика, месяц, цену, отметить проведённые занятия.\n'
            '/students 11.2026 — отчёт за выбранный месяц.\n/cancel — отменить ввод.')

    async def callback(self, data, message):
        p = data.split(':')
        try:
            action = p[1]
            if action == 'list':
                await self.students(date.fromisoformat(p[2]), int(p[3]), message)
            elif action == 'student':
                await self.student(p[2], date.fromisoformat(p[3]).replace(day=1), int(p[4]) if len(p)>4 else 0, message)
            elif action == 'lessons':
                await self.lesson_details(p[2],date.fromisoformat(p[3]),int(p[4]),message)
            elif action == 'details':
                await self.details(p[2],date.fromisoformat(p[3]),message)
            elif action == 'find':
                state=self.store.get('tutoring_search')
                if not state or state['nonce']!=p[2] or datetime.fromisoformat(state['expires'])<self.bot.now():
                    await self.bot.reply('Поиск устарел. Напишите имя ещё раз.')
                else:await self.search_choices(state,int(p[3]),message)
            elif action == 'all':
                month=date.fromisoformat(p[2])
                if self.store.get('reollity_sync'):
                    from .reollity import billing_state
                    state=billing_state(self.store,self.bot.schedule,month)
                    lines=[f'💳 К ВНЕСЕНИЮ · {month:%m.%Y}',
                           'С учётом долга, аванса и уже внесённого.']
                    lines += [r['name']+' → '+(money(r['due']) if r['due'] is not None else 'нет сверки') for r in state['students']]
                    lines.append('Всего по сверенным ученикам: '+money(state['total_due']))
                    text='\n\n'.join(lines)
                else:text=self.book.summary(month)
                await self.bot.chat.screen(text,markup([btn('👥 Выбрать ученика', f'list:{p[2]}:0')]),message)
            elif action == 'payments':
                from .reollity import bill
                student=next(s for s in self.book.roster() if s['id']==p[2])
                row=bill(self.store,self.bot.schedule,student,date.fromisoformat(p[3]))
                lines=['🧾 ПОСТУПЛЕНИЯ · '+student['name']]
                for item in (row['previous'],row['current']):
                    if not item:continue
                    lines.append(item['month']+' · '+str(len(item['payments']))+' оплат · '+money(item['paid']))
                    lines.extend(date.fromisoformat(t['day']).strftime('%d.%m.%Y')+' → '+money(t['amount']) for t in item['payments'])
                    if not item['payments']:lines.append('Поступлений не зафиксировано.')
                await self.bot.chat.screen('\n'.join(lines),markup([btn('‹ Расчёт и занятия',f'student:{p[2]}:{p[3]}')]),message)
            elif action == 'sync':
                service=self.bot.reollity
                active=getattr(service,'background_task',None)
                if service.lock.locked() or (active and not active.done()):
                    await self.bot.reply('↻ Сверка уже идёт. Остальные команды доступны.')
                    return
                if not service.configured:
                    await self.bot.reply('Reollity не подключена.');return
                month=date.fromisoformat(p[2])
                uid=p[3] if len(p)>3 else None
                async def refresh():
                    meta=await service.refresh(force=True)
                    if not meta:await self.bot.reply('Сверка пока не обновилась. Сохранены предыдущие данные.')
                    elif uid:await self.student(uid,month)
                    else:await self.students(month)
                service.background_task=self.bot.background(refresh())
                await self.bot.reply('↻ Обновляю сверку в фоне. Можно пользоваться ботом.')
            elif action == 'rate':
                self.pending(step='rate', student=p[2], month=p[3])
                await self.bot.reply('Напишите цену одного занятия с этого ученика в рублях. Например: 1800.\n'
                    'Применю только к выбранному месяцу. 0 — бесплатное занятие. /cancel — отменить.')
            elif action == 'check':
                month = date.fromisoformat(p[3])
                last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
                for event in self.book.entries(month, last, p[2]):
                    key = event_key(event)
                    if hashlib.sha256(key.encode()).hexdigest()[:12] == p[4]:
                        if event.end > self.bot.now() and not self.store.checked(key):
                            await self.bot.reply('Занятие ещё не закончилось. Отметьте проведение после него.')
                        else:
                            self.store.check(key, not self.store.checked(key))
                        break
                await self.lesson_details(p[2], month, int(p[5]), message)
            elif action in ('time','source','cancel'):
                state = self.state()
                if not state or state['id'] != p[2]:
                    await self.bot.reply('Этот шаг уже завершён или устарел. Пришлите запрос заново.')
                elif action == 'cancel':
                    self.store.set('tutoring_pending', None)
                    await self.bot.reply('Добавление отменено.')
                elif action == 'time' and state['step'] == 'time':
                    state['time'] = clock(':'.join(p[3:]))
                    await self.save(state)
                elif action == 'source' and state['step'] == 'source':
                    snapshot = state['sources'][int(p[3])]
                    day = datetime.fromisoformat(snapshot[2]).date()
                    event = next(e for e in self.book.entries(day, day) if self.book.snapshot(e) == snapshot)
                    await self.source(state, event)
            elif action == 'undo':
                changed = self.book.undo(p[2])
                await self.bot.reply('↩ Изменение отменено. Расписание и суммы восстановлены.' if changed else 'Изменение уже отменено.')
            elif action == 'auto':
                self.store.set('tutoring_monthly_report', not self.store.get('tutoring_monthly_report', True))
                await self.students(date.fromisoformat(p[2]), message=message)
            elif action == 'help':
                await self.help()
        except (ValueError, KeyError, IndexError, StopIteration) as exc:
            await self.bot.reply(str(exc) if isinstance(exc, ValueError) and str(exc) else 'Данные изменились. Откройте /students заново.')

    async def command(self, cmd, args):
        if cmd in ('/students','/lessons'):
            try:month=month_start(args,self.bot.now().date())
            except ValueError:await self.lookup(args,explicit=True)
            else:await self.students(month)
        elif cmd == '/pay':
            if args:await self.lookup(args,explicit=True)
            else:await self.students()
        elif cmd == '/lesson':
            if args.split(' ',1)[0] in ('add','delete','list'):
                return False  # Preserve the existing recurring-rule command.
            if not args:
                await self.help()
            elif not await self.request(args):
                await self.help()
        elif cmd == '/reconcile':
            await self.callback('tu:sync:'+str(self.bot.now().date().replace(day=1)),{})
        else:
            return False
        return True
