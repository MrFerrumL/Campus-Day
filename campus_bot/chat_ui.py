"""Owner-only chat screens; Bot checks identity before dispatching here."""
import calendar
from datetime import date, datetime, timedelta
import hashlib
import re
from uuid import uuid4

from .models import WEEKDAYS, at, clock, overlaps, parse_day
from .views import MENU, event_line
from .daily_plan import priority_text, task_when
from .analytics import task_analytics

SHORT = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')
MONTHS = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')


def button(text, action):
    return {'text': text, 'callback_data': 'c:' + action}


def keyboard(*rows):
    return {'inline_keyboard': list(rows)}


class ChatUI:
    def __init__(self, bot):
        self.bot, self.store = bot, bot.store

    def today(self):
        return self.bot.now().date()

    async def screen(self, text, markup, message=None):
        # Telegram's edit limit is UTF-16 units; send() safely splits long agendas.
        if message and message.get('message_id') and len(text.encode('utf-16-le')) // 2 < 3900:
            from .network import ServiceError
            try:
                await self.bot.telegram.call('editMessageText', chat_id=self.bot.config.owner_id,
                    message_id=message['message_id'], text=text, reply_markup=markup,
                    link_preview_options={'is_disabled': True})
                return
            except ServiceError as exc:
                if exc.status != 400:
                    raise
        await self.bot.reply(text, reply_markup=markup)

    async def home(self):
        today = self.today()
        await self.bot.reply(
            f'✳️ День\n{WEEKDAYS[today.weekday()].capitalize()}, {today:%d.%m.%Y}\n\n'
            '📅 Планируйте день и неделю\n'
            '🎯 Собирайте задачи и дедлайны\n'
            '🏋️ Ведите журнал тренировок, питания и сна\n\n'
            'Откройте нужный раздел ниже. «Мой профиль» покажет аккаунт и настройки доступа.',
            reply_markup=MENU,
        )

    async def week(self, day, message=None):
        first = day - timedelta(days=day.weekday())
        lines, days = [f'🗓 РАСПИСАНИЕ НЕДЕЛИ\n'
                       f'{first:%d.%m.%Y} — {first+timedelta(days=6):%d.%m.%Y}\n'
                       f'🎓 {self.store.get("group_name")}'], []
        for offset in range(7):
            current = first + timedelta(days=offset)
            events, note, _ = await self.bot.schedule.day(current)
            sections = [f'━━ {WEEKDAYS[offset].upper()} · {current:%d.%m}'
                        + (' · сегодня' if current == self.today() else '') + ' ━━']
            for source, label in (('university', '🎓 Вуз'), ('personal', '📚 Дополнительные занятия')):
                entries = [e for e in events if e.source == source]
                content = '\n'.join(event_line(e) if source == 'university' else
                                    ('❌ ' if e.cancelled else '') + e.time_label+' · '+e.title
                                    for e in entries)
                if not content:
                    content = ('Данные не получены — проверьте сайт.' if source == 'university' and note
                               else 'Пар нет.' if source == 'university' else 'Занятий нет.')
                sections.append(label+'\n'+content)
            if note:
                sections.append(note)
            lines.append('\n\n'.join(sections))
            days.append(button(f'{SHORT[offset]} · {current:%d.%m}', f'day:{current}'))
        rows = [days[:4], days[4:]]
        rows += [[button('‹ Неделя', f'week:{first-timedelta(days=7)}'),
                  button('Сейчас', f'week:{self.today()}'), button('Неделя ›', f'week:{first+timedelta(days=7)}')],
                 [button('📆 Месяц', f'month:{day}'), button('🔎 Другая дата', 'date:day')]]
        await self.screen('\n\n'.join(lines), keyboard(*rows), message)

    async def month(self, day, purpose='day', kind='task', message=None):
        first = day.replace(day=1)
        previous = (first-timedelta(days=1)).replace(day=1)
        following = (first+timedelta(days=32)).replace(day=1)
        label = 'Выберите день для расписания.' if purpose == 'day' else 'На какой день добавить?'
        rows = [[button(s, 'noop') for s in SHORT]]
        for week in calendar.Calendar().monthdatescalendar(day.year, day.month):
            row = []
            for d in week:
                action = f'day:{d}' if purpose == 'day' else f'new:{kind}:{d}'
                row.append(button(('•' if d == self.today() else '') + str(d.day), action)
                           if d.month == day.month else button('·', 'noop'))
            rows.append(row)
        rows += [[button('‹', f'month:{previous}:{purpose}:{kind}'),
                  button('Сегодня', f'day:{self.today()}' if purpose == 'day' else f'new:{kind}:{self.today()}'),
                  button('›', f'month:{following}:{purpose}:{kind}')],
                 [button('🔎 Ввести дату', f'date:{purpose}:{kind}'), button('🗓 Неделя', f'week:{day}')]]
        await self.screen(f'📆 {MONTHS[day.month-1].upper()} {day.year}\n\n{label}', keyboard(*rows), message)

    async def day(self, day, message=None):
        text = await self.bot.day_text(day)
        rows = [[button('‹ День', f'day:{day-timedelta(days=1)}'), button('Неделя', f'week:{day}'),
                 button('День ›', f'day:{day+timedelta(days=1)}')],
                [button('➕ Задача', f'new:task:{day}'), button('🗓 План', f'new:event:{day}')],
                [button('📋 План и подпункты', f'daily:{day}'), button('✅ Занятия', f'checks:{day}:1')],
                [button('🕊 Окна', f'free:{day}'), button('📆 Месяц', f'month:{day}')]]
        await self.screen(text, keyboard(*rows), message)

    def tasks(self, done=False):
        projects = {p['id']: p for p in self.store.projects()}
        return [i for i in self.store.items('task', include_done=True) if bool(i['done']) == done and not i['skipped']
                and (not i['project'] or projects.get(i['project'], {}).get('status') not in (None, 'done', 'dropped'))]

    def failed_tasks(self):
        projects={p['id']:p for p in self.store.projects()}
        return [i for i in self.store.items('task',include_done=True) if i['skipped'] and
                (not i['project'] or projects.get(i['project'],{}).get('status') not in (None,'done','dropped'))]

    async def task_list(self, scope='all', page=1, message=None):
        items = self.failed_tasks() if scope=='failed' else self.tasks(scope == 'done')
        if scope=='important':
            items=[r for r in self.tasks() if r['priority']]
        if scope not in ('all', 'done', 'overdue', 'failed', 'important'):
            day = date.fromisoformat(scope)
            items = [i for i in items if datetime.fromisoformat(i['due']).date() == day]
            label = f'ДЕЛА НА {day:%d.%m.%Y}'
        else:
            label = {'all': 'МОИ ЗАДАЧИ', 'done': 'ВЫПОЛНЕНО', 'overdue': 'ПРОСРОЧЕНО','failed':'НЕ СДЕЛАНО','important':'ВАЖНЫЕ ЗАДАЧИ'}[scope]
            if scope == 'overdue':
                items = [i for i in items if datetime.fromisoformat(i['due']) < self.bot.now()]
        pages = max(1, (len(items)+5)//6)
        page = max(1, min(page, pages))
        lines, rows = [f'📋 {label} · {page}/{pages}'], []
        for i in items[(page-1)*6:page*6]:
            due = datetime.fromisoformat(i['due'])
            icon='✅' if i['done'] else '❌' if i['skipped'] else '▫️'
            lines.append(f'{icon} {"🚨 " if i["priority"] else ""}#{i["id"]} · {i["title"]}\n'
                         +task_when(i)+(' · просрочено' if not i['done'] and not i['skipped'] and due < self.bot.now() else ''))
            rows.append([button(f'Открыть #{i["id"]}', f'task:{i["id"]}'),
                         button('↩ Вернуть' if i['done'] else '✓ Готово', f'status:{i["id"]}:{0 if i["done"] else 1}')])
        if not items:
            lines.append('Здесь пока ничего нет. Можно добавить новое дело кнопкой ниже.')
        rows += [[button('‹', f'tasks:{scope}:{max(1,page-1)}'), button('›', f'tasks:{scope}:{min(pages,page+1)}')],
                 [button('Сегодня', f'tasks:{self.today()}:1'), button('Все', 'tasks:all:1'), button('Готово', 'tasks:done:1')],
                 [button('❌ Не сделал', 'tasks:failed:1'),button('⚠ Просрочено', 'tasks:overdue:1'), button('➕ Задача', 'choose:task')]]
        await self.screen('\n\n'.join(lines), keyboard(*rows), message)

    def item(self, uid):
        return next((i for i in self.tasks()+self.tasks(True)+self.failed_tasks() if i['id'] == int(uid)), None)

    async def task_card(self, uid, message=None):
        i = self.item(uid)
        if not i:
            await self.bot.reply('Задача больше недоступна. Откройте /tasks.')
            return
        due = datetime.fromisoformat(i['due'])
        await self.screen(f'{"🚨 ВАЖНАЯ ЗАДАЧА" if i.get("priority") else "🎯 ЗАДАЧА"} #{i["id"]}\n\n{i["title"]}\n\n'
                          +('На день · ' if i['all_day'] else 'Время · ')+task_when(i)+'\n'
                          +f'Статус · {"выполнено ✅" if i["done"] else "не сделано ❌" if i["skipped"] else "в работе ▫️"}'
                          + ('\n\n'+i['note'][:1800] if i.get('note') else ''), keyboard(
            [button('↩ Вернуть в работу' if i['done'] else '✓ Выполнено', f'status:{uid}:{0 if i["done"] else 1}')],
            [button('↩ Вернуть в работу' if i['skipped'] else '❌ Не сделал',f'status:{uid}:{"0" if i["skipped"] else "failed"}'),
             button('Снять важность' if i['priority'] else '🚨 Важно',f'priority:{uid}:{0 if i["priority"] else 1}')],
            [button('📅 Перенести', f'move:{uid}'), button('✎ Название', f'rename:{uid}')],
            [button('📋 Список', 'tasks:all:1'), button('Расписание дня', f'day:{due.date()}')]), message)

    async def choose(self, kind):
        self.store.set('chat_pending', None)
        today = self.today()
        await self.bot.reply('➕ НОВОЕ ДЕЛО\n\nВыберите дату.', reply_markup=keyboard(
            [button('Сегодня', f'new:{kind}:{today}'), button('Завтра', f'new:{kind}:{today+timedelta(days=1)}')],
            [button('📆 Календарь', f'month:{today}:new:{kind}'), button('🔎 Ввести дату', f'date:new:{kind}')]))

    def pending(self, **values):
        state = dict(values, nonce=uuid4().hex[:8], expires=(self.bot.now()+timedelta(minutes=30)).isoformat())
        self.store.set('chat_pending', state)
        return state

    def state(self):
        state = self.store.get('chat_pending')
        if state and datetime.fromisoformat(state['expires']) < self.bot.now():
            self.store.set('chat_pending', None)
            return None
        return state

    async def begin(self, kind, day, uid=None):
        if day < self.today():
            await self.bot.reply('Выберите сегодняшний или будущий день. /calendar — календарь.')
            return
        state = self.pending(kind=kind, day=str(day), step='time' if uid else 'title', uid=uid)
        if uid:
            item = self.item(uid)
            if not item or item['done']:
                self.store.set('chat_pending', None)
                await self.bot.reply('Можно перенести только активную задачу.')
                return
            state['title'] = item['title']
            self.store.set('chat_pending', state)
            await self.ask_time(state)
        else:
            label = {'task': 'задачи', 'event': 'плана', 'reminder': 'напоминания'}[kind]
            await self.bot.reply(f'✍️ {day:%d.%m.%Y} · {WEEKDAYS[day.weekday()]}\n\n'
                f'Напишите название {label}.\nМожно сразу со временем: «18:30 Сдать лабораторную».\n'
                'Без времени предложу варианты. /cancel — отменить.',
                reply_markup=keyboard([button('Отмена', 'cancel:'+state['nonce'])]))

    async def ask_time(self, state):
        rows = [[button(t, f'flow:{state["nonce"]}:time:{t}') for t in ('12:00', '18:00', '23:59')],
                [button('Отмена', 'cancel:'+state['nonce'])]]
        await self.bot.reply(f'🕐 {state["title"]}\n{date.fromisoformat(state["day"]):%d.%m.%Y}\n\n'
            'Во сколько? Выберите кнопку или отправьте время, например 16:30.', reply_markup=keyboard(*rows))

    async def save(self, state):
        due = at(date.fromisoformat(state['day']), state['time'], self.bot.config.timezone)
        if due <= self.bot.now():
            state['step'] = 'time'
            self.store.set('chat_pending', state)
            await self.bot.reply('Это время уже прошло. Напишите будущее время или /cancel.')
            return
        if state.get('uid'):
            uid = state['uid']
            item = self.item(uid)
            if not item or item['done']:
                self.store.set('chat_pending', None)
                await self.bot.reply('Задача уже выполнена или удалена. Откройте /tasks.')
                return
            self.store.move(uid, due.isoformat())
        elif state.get('mail_action_id'):
            uid=self.store.accept_mail_task(state['mail_action_id'],state['mail_candidate'],due.isoformat())
        else:
            uid = self.store.add_item(state['kind'], state['title'], due.isoformat(), state.get('duration', 0),
                                      note=state.get('note',''),priority=state.get('priority',0))
        self.store.set('chat_pending', None)  # A second tap cannot create the same task again.
        await self.bot.reply(f'✅ СОХРАНЕНО #{uid}\n\n{state["title"]}\n{due:%d.%m.%Y · %H:%M}',
            reply_markup=keyboard([button('📅 Этот день', f'day:{due.date()}'),
                button('➕ Ещё задачу', f'new:task:{due.date()}')]))
        if state['kind'] == 'event':
            events, _, _ = await self.bot.schedule.day(due.date())
            if any(any(e.uid == f'plan:{uid}' for e in pair) for pair in overlaps(events)):
                await self.bot.reply('⚠️ План пересекается с другим событием. Проверьте расписание выбранного дня.')

    async def input(self, text):
        previous = self.store.get('chat_pending')
        state = self.state()
        if not state:
            if previous:
                await self.bot.reply('Время ввода истекло (30 минут). /add — начать новую задачу.')
                return True
            return False
        try:
            step = state['step']
            if step == 'date':
                day = parse_day(text, self.today())
                if state.get('suggested_title'):
                    if day<self.today():raise ValueError('Дата в прошлом')
                    state.update(day=str(day),step='time')
                    self.store.set('chat_pending',state)
                    await self.ask_time(state)
                    return True
                self.store.set('chat_pending', None)
                if state['purpose'] == 'day':
                    await self.day(day)
                else:
                    await self.begin(state['kind'], day, state.get('uid'))
            elif step == 'rename':
                if not 1 <= len(text.strip()) <= 300:
                    raise ValueError()
                uid = state['uid']
                if not self.item(uid):
                    raise ValueError()
                with self.store.db:
                    name,priority=priority_text(text)
                    self.store.db.execute("UPDATE items SET title=?,priority=MAX(priority,?) WHERE id=? AND kind='task'", (name,priority,uid))
                self.store.set('chat_pending', None)
                await self.task_card(uid)
            elif step == 'title':
                text,priority=priority_text(text)
                match = re.fullmatch(r'(\d{1,2}:\d{2})\s+(.+)', text, re.S)
                name,extra_priority=priority_text(match[2] if match else text)
                if not 1 <= len(name) <= 300:
                    raise ValueError()
                state.update(title=name, step='time',priority=max(priority,extra_priority))
                self.store.set('chat_pending', state)
                if match:
                    await self.time(state, match[1])
                else:
                    await self.ask_time(state)
            elif step == 'time':
                await self.time(state, text)
            elif step == 'duration':
                duration = int(text)
                if not 5 <= duration <= 1440:
                    raise ValueError()
                state['duration'] = duration
                await self.save(state)
            return True
        except (ValueError, KeyError, TypeError):
            await self.bot.reply('Не удалось разобрать ответ. Проверьте дату, время или название. /cancel — отменить.')
            return True

    async def time(self, state, value):
        state['time'] = clock(value)
        if at(date.fromisoformat(state['day']), state['time'], self.bot.config.timezone) <= self.bot.now():
            await self.bot.reply('Это время уже прошло. Напишите другое время или /cancel.')
            return
        if state['kind'] == 'event':
            state['step'] = 'duration'
            self.store.set('chat_pending', state)
            await self.bot.reply('⏱ Сколько минут займёт план? Можно ввести число от 5 до 1440.',
                reply_markup=keyboard([button(str(n)+' мин', f'flow:{state["nonce"]}:duration:{n}') for n in (30,60,120)]))
        else:
            await self.save(state)

    async def checks(self, day, page=1, message=None):
        events, _, _ = await self.bot.schedule.day(day)
        events = [e for e in events if not e.cancelled]
        page = max(1, min(page, max(1, (len(events)+5)//6)))
        rows = []
        for e in events[(page-1)*6:page*6]:
            key = e.uid+'|'+str(e.start.date())
            digest = hashlib.sha256(key.encode()).hexdigest()[:12]
            rows.append([button(('✅ ' if self.store.checked(key) else '▫️ ')+e.time_label+' '+e.title[:45],
                                f'check:{day}:{digest}:{page}')])
        rows += [[button('‹', f'checks:{day}:{max(1,page-1)}'), button('›', f'checks:{day}:{page+1}')],
                 [button('📅 Расписание', f'day:{day}')]]
        await self.screen(f'✅ ВЫПОЛНЕНИЕ · {day:%d.%m}\n\nНажмите на занятие, чтобы поставить или снять галочку. '
                          'Отметки синхронизируются с приложением.' + ('\nСобытий нет.' if not events else ''), keyboard(*rows), message)

    async def stats(self, period='week', selected=None, message=None):
        now=self.bot.now()
        selected=selected or self.today()
        if period=='day':
            first=last=selected
        elif period=='month':
            first=selected.replace(day=1)
            last=(first+timedelta(days=32)).replace(day=1)-timedelta(days=1)
        elif period=='week':
            first=selected-timedelta(days=selected.weekday())
            last=first+timedelta(days=6)
        else:
            raise ValueError('Период: day, week или month')
        result=task_analytics(self.store.items('task',include_done=True),first,last,now)
        percent=round(result['done']/result['total']*100) if result['total'] else 0
        filled=round(percent/10)
        lines=[f'📊 МОЯ АНАЛИТИКА · {first:%d.%m} — {last:%d.%m}',
               f'{"▰"*filled}{"▱"*(10-filled)} {percent}% плана\n'
               f'✅ Сделано: {result["done"]}/{result["total"]} · ❌ Не сделано: {result["failed"]}\n'
               f'▫️ В работе: {result["pending"]}\n'
               f'Группы не дублируют подсчёт подпунктов.',
               f'🔥 Серия дней с выполненными задачами: {result["streak"]}\n'
               f'За период зафиксировано выполнений: {result["completed"]}']
        important=result['important'][:6]
        lines.append('🚨 ВАЖНОЕ СДЕЛАНО\n'+('\n'.join('✅ '+r['title'] for r in important) or 'Пока нет зафиксированных выполнений важных задач.'))
        if result['planned_minutes']:
            lines.append(f'⏱ Закрытые блоки плана: {result["closed_minutes"]} из {result["planned_minutes"]} мин. Это плановая длительность, не замер работы.')
        if period!='day':
            lines.append('ПО ДНЯМ\n'+'\n'.join(f'{r["day"][8:10]}.{r["day"][5:7]} · ✅ {r["done"]}/{r["total"]} · ❌ {r["failed"]}' for r in result['days'] if r['total']))
        if period=='week':
            total=done=minutes=unknown=0
            for n in range(7):
                events,_,_=await self.bot.schedule.day(first+timedelta(days=n))
                for e in events:
                    if e.cancelled:continue
                    total+=1
                    done+=self.store.checked(e.uid+'|'+str(e.start.date()))
                    if not e.all_day:
                        minutes+=int((e.end-e.start).total_seconds()/60)
                        unknown+=e.start==e.end
            lines.append(f'📚 Отмечено событий: {done}/{total}\nЗапланировано: {minutes//60} ч {minutes%60:02} мин (включая пересечения).'
                         +(f' У {unknown} событий длительность неизвестна.' if unknown else ''))
        await self.screen('\n\n'.join(lines),keyboard(
            [button('День',f'stats:day:{selected}'),button('Неделя',f'stats:week:{selected}'),button('Месяц',f'stats:month:{selected}')],
            [button('📋 План дня',f'daily:{selected}'),button('🚨 Важные', 'tasks:important:1')]),message)

    async def callback(self, data, message):
        p = data.split(':')
        action = p[1]
        day = lambda value: date.fromisoformat(value)
        if action == 'stats':
            await self.stats(p[2],day(p[3]) if len(p)>3 else None,message)
            return
        if action == 'daily':
            await self.bot.daily_plans.show(p[2],message)
            return
        if action == 'priority':
            self.store.set_priority(int(p[2]),int(p[3]))
            await self.task_card(p[2],message)
            return
        if action == 'noop':
            return
        if action in ('day','week'):
            await getattr(self, action)(day(p[2]), message)
        elif action == 'month':
            await self.month(day(p[2]), p[3] if len(p)>3 else 'day', p[4] if len(p)>4 else 'task', message)
        elif action == 'choose':
            await self.choose(p[2])
        elif action == 'new':
            if p[2] not in ('task','event','reminder'):
                raise ValueError()
            await self.begin(p[2], day(p[3]))
        elif action == 'date':
            self.pending(step='date', purpose=p[2], kind=p[3] if len(p)>3 else 'task')
            await self.bot.reply('🔎 Напишите дату: 02.11, 2026-11-02, завтра или пятница. /cancel — отменить.')
        elif action == 'cancel':
            state = self.state()
            if state and state['nonce'] == p[2]:
                self.store.set('chat_pending', None)
                await self.bot.reply('Добавление отменено. /menu — главное меню.')
        elif action == 'flow':
            state = self.state()
            if not state or state['nonce'] != p[2] or state['step'] != p[3]:
                await self.bot.reply('Этот шаг уже завершён или устарел. /add — новая задача.')
            elif p[3] == 'time':
                await self.time(state, ':'.join(p[4:]))
            elif p[3] == 'duration':
                await self.input(p[4])
        elif action == 'tasks':
            await self.task_list(p[2], int(p[3]), message)
        elif action == 'task':
            await self.task_card(int(p[2]), message)
        elif action == 'status':
            if self.item(p[2]) and p[3] in ('0','1','failed'):
                self.store.set_task_status(int(p[2]),{'0':'pending','1':'done','failed':'failed'}[p[3]],self.bot.now())
            await self.task_card(p[2], message)
        elif action == 'move':
            if self.item(p[2]):
                self.pending(step='date', purpose='new', kind='task', uid=int(p[2]))
                await self.bot.reply('📅 На какой день перенести? Напишите дату, «завтра» или день недели. Затем выберем время.')
        elif action == 'rename':
            if self.item(p[2]):
                self.pending(step='rename', uid=int(p[2]))
                await self.bot.reply('✎ Напишите новое название задачи. /cancel — отменить.')
        elif action == 'checks':
            await self.checks(day(p[2]), int(p[3]), message)
        elif action == 'check':
            d = day(p[2])
            events, _, _ = await self.bot.schedule.day(d)
            for e in events:
                key = e.uid+'|'+str(e.start.date())
                if not e.cancelled and hashlib.sha256(key.encode()).hexdigest()[:12] == p[3]:
                    self.store.check(key, not self.store.checked(key))
                    break
            await self.checks(d, int(p[4]), message)
        elif action == 'free':
            await self.bot.command('/free', p[2]+' 60')
        elif action == 'focus':
            await self.bot.reply('🍅 ВРЕМЯ ДЛЯ ФОКУСА\n\nВыберите длительность. Бот напомнит сделать перерыв.',
                reply_markup=keyboard([button(str(n)+' мин', f'timer:{n}') for n in (15,25,50)]))
        elif action == 'timer':
            if int(p[2]) not in (15,25,50):
                raise ValueError()
            await self.bot.command('/focus', p[2])

    async def command(self, cmd, args):
        if cmd == '/cancel':
            self.store.set('chat_pending', None)
            await self.bot.reply('Текущее добавление отменено. Выберите действие на клавиатуре.', reply_markup=MENU)
        elif cmd == '/menu':
            self.store.set('chat_pending', None)
            await self.home()
        elif cmd in ('/calendar','/week','/month'):
            self.store.set('chat_pending', None)
            d = parse_day(args, self.today()) if args else self.today()
            await (self.month(d) if cmd == '/month' else self.week(d))
        elif cmd in ('/today','/tomorrow','/day'):
            self.store.set('chat_pending', None)
            d = self.today()+timedelta(days=1) if cmd == '/tomorrow' else parse_day(args, self.today()) if args else self.today()
            await self.day(d)
        elif cmd in ('/add','/plan','/remind') and not args:
            await self.choose({'/add':'task','/plan':'event','/remind':'reminder'}[cmd])
        elif cmd == '/tasks':
            self.store.set('chat_pending', None)
            await self.task_list(page=int(args) if args else 1)
        elif cmd == '/stats':
            tokens=args.split()
            await self.stats(tokens[0] if tokens else 'week',parse_day(tokens[1],self.today()) if len(tokens)>1 else None)
        elif cmd == '/focus' and not args:
            await self.callback('c:focus', {})
        else:
            return False
        return True
