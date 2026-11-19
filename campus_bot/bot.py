import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta
import logging
import os
from uuid import uuid4

from . import hackathons, web_login
from .chat_ui import ChatUI
from .daily_plan import DailyPlans, priority_text
from .tutoring import Tutoring
from .reollity import ReollitySync
from .access import AccountAccess, AccountStore, accounts, allowed_ids
from .health import HEARTBEAT
from .jobs import Scheduler, occurrences
from .mail import Mail, normalize
from .models import DAY_CODES, WEEKDAYS, at, clock, free_slots, parse_day
from .network import ServiceError
from .views import HELP, MENU, agenda, event_line

log = logging.getLogger(__name__)
BUTTONS = {"📅 Сегодня": "/today", "🌅 Завтра": "/tomorrow", "⏭ Следующее": "/next",
           "📱 Приложение": "/app", "👤 Мой профиль": "/profile",
           "🌤 Погода": "/weather", "🕊 Свободное время": "/free", "🎯 Задачи": "/tasks",
           "➕ Задача": "/add", "⚙️ Настройки": "/settings", "🏆 Хакатоны": "/hack",
           "🗓 Расписание": "/calendar", "🗓 План": "/plan", "🍅 Фокус": "/focus",
           "📊 Моя неделя": "/stats", "📊 Аналитика":"/stats", "📋 План дня":"/dayplan", "🏠 Меню": "/menu",
           "👥 Ученики и оплата": "/students", "🏋️ Зал":"/gym", "🍽 Питание":"/food",
           "🌙 Сон":"/sleep", "🤖 Помощник":"/ai", "💼 Зарплата":"/zp"}


def title(value):
    value = value.strip()
    if not 1 <= len(value) <= 300:
        raise ValueError("Название должно содержать от 1 до 300 символов")
    return value


class Bot:
    def __init__(self, config, store, schedule, weather, telegram):
        self.config, self.store, self.schedule = config, store, schedule
        self.weather, self.telegram = weather, telegram
        self.scheduler = Scheduler(self)
        self.mail = Mail(self)
        self.chat = ChatUI(self)
        self.daily_plans = DailyPlans(self)
        self.tutoring = Tutoring(self)
        self.reollity = ReollitySync(self)
        from .assistant import Assistant
        self.assistant = Assistant(self)
        self.primary_owner_id = config.owner_id
        self._background_tasks = set()

    def now(self):
        return datetime.now(self.config.timezone)

    async def day_text(self, day, weather=True, force=False):
        events, note, _ = await self.schedule.day(day, force)
        now = self.now()
        forecast = await self.weather.today() if weather and day == now.date() else ""
        outlook = hackathons.outlook(self.store, now) if day == now.date() else ""
        return agenda(day, events, note, self.store, forecast, outlook)

    async def reply(self, text, **kwargs):
        await self.telegram.send(self.config.owner_id, text, **kwargs)

    def background(self, coroutine):
        task=asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        def finished(value):
            self._background_tasks.discard(value)
            if not value.cancelled() and value.exception():
                log.warning('Фоновая операция упала',exc_info=value.exception())
        task.add_done_callback(finished)
        return task

    def mini_app_url(self):
        # The server .env is the source of truth; the stored value is only the
        # old fallback for a local Cloudflare tunnel (connect_miniapp.py).
        return os.getenv('MINI_APP_URL','') or self.store.get('mini_app_url') or ''

    async def bind_app_menu(self, uid):
        url=self.mini_app_url()
        if not url.startswith('https://'):return
        try:
            await self.telegram.call('setChatMenuButton',chat_id=uid,
                                     menu_button={'type':'web_app','text':'Календарь','web_app':{'url':url}})
        except ServiceError:
            log.warning('Кнопка приложения пока не обновлена; повтор при /app.')

    async def acknowledge(self, callback_id):
        try:
            await self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
        except ServiceError as exc:
            if exc.status!=400:log.warning('Telegram задержал подтверждение кнопки.')

    async def handle(self, update):
        callback = update.get('callback_query')
        message = (callback or {}).get('message') if callback else update.get('message')
        if not message or message.get('chat',{}).get('type')!='private':
            return
        user = (callback or message).get('from',{})
        sender = user.get('id')
        if message['chat'].get('id')!=sender:
            return
        text = message.get('text','').strip()
        command,_,argument = text.partition(' ')
        if not callback and command.split('@')[0]=='/start' and argument.startswith('connect_'):
            try:
                record,created = AccountAccess(self.store).claim(argument[8:],user,self.now())
                self.background(self.bind_app_menu(sender))
                await self.telegram.send(sender,'✅ Аккаунт подключён к общему календарю.\n'
                    'Доступны расписание, задачи, ученики, оплаты, письма и Mini App.\n'
                    'Меню: /menu · приложение: /app. Уведомления включены.',reply_markup=MENU)
                if created:
                    await self.telegram.send(self.config.owner_id,'✅ @'+record['username']+
                        ' подключён к вашему календарю с полным доступом.\n/accounts — управление доступом.')
            except ValueError as exc:
                await self.telegram.send(sender,str(exc))
            return
        if command=='/accounts' or (callback and callback.get('data','').startswith('acct:')):
            if sender not in allowed_ids(self.store,self.config.owner_id):
                return
            if callback:
                self.background(self.acknowledge(callback['id']))
                await asyncio.sleep(0)
                action,uid = callback['data'].removeprefix('acct:').split(':')
                if action=='revoke':
                    AccountAccess(self.store).revoke(int(uid))
            records=accounts(self.store)
            await self.telegram.send(sender,'👤 ДОСТУП К КАЛЕНДАРЮ\n\nОсновной аккаунт остаётся подключённым.\n'+
                ('\n'.join('@'+r['username']+' · полный доступ' for r in records) if records else 'Других аккаунтов нет.'),
                reply_markup={'inline_keyboard':[[{'text':'Отключить @'+r['username'],'callback_data':'acct:revoke:'+str(r['id'])}]
                                                for r in records]})
            return
        if sender!=self.config.owner_id and sender in allowed_ids(self.store,self.config.owner_id):
            child = Bot(replace(self.config,owner_id=sender),AccountStore(self.store,sender),
                        self.schedule,self.weather,self.telegram)
            child.primary_owner_id = self.config.owner_id
            child.reollity = self.reollity
            child.assistant.busy = self.assistant.busy
            child.mail.lock = self.mail.lock
            child.mail.connect = self.mail.connect
            child._background_tasks = self._background_tasks
            child.now = self.now
            await child._handle_owner(update)
            return
        await self._handle_owner(update)

    async def notify(self, text, delivery_key=None, **kwargs):
        targets=[self.primary_owner_id]+[a['id'] for a in accounts(self.store) if a.get('notifications',True)
                                        and a['id']!=self.primary_owner_id]
        for uid in targets:
            key = f'{delivery_key}:to:{uid}' if delivery_key else None
            if key and self.store.delivered(key):
                continue
            try:
                await self.telegram.send(uid,text,**kwargs)
            except ServiceError as exc:
                if exc.status==403 and uid!=self.primary_owner_id:
                    AccountAccess(self.store).stop_notifications(uid)
                    continue
                raise
            if key:self.store.mark(key,self.now().isoformat())

    async def _handle_owner(self, update):
        callback = update.get("callback_query")
        message = (callback or {}).get("message") if callback else update.get("message")
        if not message or message.get("chat", {}).get("type") != "private":
            return
        sender = (callback or message).get("from", {}).get("id")
        text = message.get("text", "").strip()
        if not callback and (text.split(" ")[0].split("@")[0].lower() == "/id" or text == "🆔 Мой ID"):
            await self.telegram.send(message["chat"]["id"], f"Ваш Telegram ID: {sender}")
            return
        if not self.config.owner_id:
            if text == "/start":
                await self.telegram.send(message["chat"]["id"],
                                         "Для настройки отправьте /id, запишите число в OWNER_ID файла .env "
                                         "и перезапустите бота. Доступ к расписанию пока закрыт.")
            return
        if sender != self.config.owner_id or message["chat"]["id"] != self.config.owner_id:
            if callback:
                await self.telegram.call("answerCallbackQuery", callback_query_id=callback["id"], text="Личный бот")
            return
        if callback:
            self.background(self.acknowledge(callback['id']))
            await asyncio.sleep(0)
            data = callback.get("data", "")
            if data.startswith(('ai:ok:','ai:no:')):
                from . import assistant_web
                uid=data[6:]
                try:
                    if data.startswith('ai:ok:'):
                        output=assistant_web.confirm(self.store,self.config.owner_id,uid,self.now())
                        markup={'inline_keyboard':[[{'text':'↩ Отменить изменения','callback_data':'ai:undo:'+output['run']}]]} if output.get('run') else None
                        await self.reply(output['message'],**({'reply_markup':markup} if markup else {}))
                    else:
                        await self.reply(assistant_web.cancel(self.store,self.config.owner_id,uid,self.now())['message'])
                except ValueError as exc:await self.reply(str(exc))
                return
            if data.startswith('ai:undo:'):
                from .assistant import undo
                try:await self.reply(undo(self.store,data.removeprefix('ai:undo:'),self.config.owner_id))
                except ValueError as exc:await self.reply(str(exc))
                return
            if data.startswith('zp:'):
                from .salary_chat import callback as salary_button
                await salary_button(self, data, message)
                return
            if data.startswith('w:'):
                from .wellness_chat import callback as journal_button
                await journal_button(self, data)
                return
            if data.startswith('tu:'):
                await self.tutoring.callback(data, message)
                return
            if data.startswith('dp:'):
                try:
                    await self.daily_plans.callback(data,message)
                except (ValueError,KeyError,IndexError,TypeError):
                    await self.reply('Задача или план изменились. Откройте /dayplan.')
                return
            if data.startswith('mail:add:'):
                from .mail_events import add_from_mail
                try:
                    await add_from_mail(self,data)
                except (ValueError,KeyError,IndexError,TypeError):
                    await self.reply('Не удалось добавить срок из письма. Выберите дату через /add.')
                return
            if data.startswith('c:'):
                try:
                    await self.chat.callback(data, message)
                except (ValueError, IndexError, KeyError, TypeError):
                    await self.reply('Кнопка устарела или данные изменились. /menu — открыть меню заново.')
                return
            if data.startswith("hk:"):
                try:
                    await self.hack_callback(data, message)
                except (ValueError, IndexError, KeyError, StopIteration):
                    await self.reply("Этот этап или хакатон уже удалён. Список: /hack")
                return
            if data.startswith("mail:mute:"):
                text = "/mail mute " + data.split(":", 2)[2]
            elif data.startswith("done:"):
                text = "/done " + data.split(":")[1]
            elif data.startswith("snooze:"):
                uid = int(data.split(":")[1])
                due = self.now() + timedelta(hours=1)
                text = f"/move {uid} {due:%Y-%m-%d %H:%M}"
            elif data in ("/today", "/tomorrow", "/settings", "/pause", "/resume") or data.startswith(("/tasks ", "/reminders ")):
                text = data
            else:
                return
        text = BUTTONS.get(text, text)
        if not callback:
            from .calendar_import import is_calendar_link
            if is_calendar_link(text):
                await self.import_calendar(text)
                return
        if text.startswith('/'):
            self.store.set('tutoring_pending', None)
        if not text.startswith('/') and await self.tutoring.request(text):
            return
        if not text.startswith('/') and await self.tutoring.input(text):
            return
        if text.startswith('/dayplan ') and '\n' in text:
            text='План на '+text.partition(' ')[2]
        if not text.startswith('/') and await self.daily_plans.handle_text(text):
            return
        if not text.startswith('/') and await self.chat.input(text):
            return
        if not text.startswith('/'):
            from .food_chat import text_input as food_text
            from .recipes_chat import text_input as recipe_link
            from .activity_chat import text_input as activity_text
            if await recipe_link(self, text) or await activity_text(self, text) or await food_text(self, text):
                return
        if not text.startswith('/') and await self.tutoring.lookup(text):
            return
        if not text.startswith('/') and await self.assistant.accept(text,f'telegram:{sender}:{message.get("message_id",uuid4().hex)}'):
            return
        cmd, _, args = text.partition(" ")
        cmd, args = cmd.split("@")[0].lower(), args.strip()
        if text.startswith('/'):
            self.store.set('chat_pending', None)
        try:
            await self.command(cmd, args)
        except (ValueError, IndexError, KeyError):
            await self.reply("Не удалось разобрать команду. Проверьте дату ГГГГ-ММ-ДД, время ЧЧ:ММ "
                             "и аргументы. Примеры: /help")

    async def import_calendar(self, link):
        from . import calendar_import
        try:
            url = calendar_import.feed_url(link)
        except ValueError as exc:
            await self.reply(str(exc))
            return
        self.background(self.finish_calendar_import(url))
        await self.reply("Загружаю расписание. Результат появится здесь.")

    async def finish_calendar_import(self, url):
        from . import calendar_import
        try:
            source, events = await asyncio.to_thread(calendar_import.fetch, url, self.now())
            result = calendar_import.summary(calendar_import.apply(self.store, source, events))
        except ValueError as exc:
            result = str(exc)
        await self.reply(result)

    async def command(self, cmd, args):
        now, tz = self.now(), self.config.timezone
        today = now.date()
        if cmd == '/import':
            if args:
                await self.import_calendar(args)
            else:
                from .calendar_import import INSTRUCTIONS
                await self.reply(INSTRUCTIONS)
            return
        if await self.assistant.command(cmd,args):return
        if cmd in ('/steps','/activity','/weight'):
            from .activity_chat import command as activity_command
            await activity_command(self, cmd, args)
            return
        if cmd in ('/zp', '/salary'):
            from .salary_chat import command as salary_command
            await salary_command(self, args)
            return
        if cmd == '/recipes':
            from .recipes_chat import menu as recipes_menu
            await recipes_menu(self)
            return
        if cmd in ('/gym','/sleep','/food','/kcal'):
            from .wellness_chat import command
            await command(self,cmd,args)
            return
        if await self.tutoring.command(cmd, args):
            return
        if cmd in ('/dayplan','/report'):
            await self.daily_plans.show(parse_day(args,today) if args else today)
            return
        if await self.chat.command(cmd, args):
            return
        if cmd == "/profile":
            await self.profile()
        elif cmd == "/start":
            self.store.set("subscribed", True)
            self.store.set("notifications", True)
            await self.chat.home()
            await self.chat.day(today)
        elif cmd == "/app":
            self.background(self.bind_app_menu(self.config.owner_id))
            url = self.mini_app_url()
            if url.startswith('https://'):
                await self.reply('📅 Ваш календарь, задачи и занятия',reply_markup={'inline_keyboard':[[
                    {'text':'Открыть приложение','web_app':{'url':url}}]]})
            else:
                await self.reply('Адрес Mini App ещё не настроен.')
        elif cmd == "/invite":
            if self.config.owner_id != self.primary_owner_id:
                await self.reply('Приглашать может только основной аккаунт.')
                return
            bot_name = self.store.get('bot_username')
            if not args or not bot_name:
                await self.reply('Напишите: /invite @username — ссылка подключит этот аккаунт к календарю.')
                return
            token = AccountAccess(self.store).issue(args, self.now())
            await self.reply(f'🔗 Ссылка для @{args.strip().lstrip("@")} действует 24 часа и только для этого аккаунта:\n'
                             f'https://t.me/{bot_name}?start=connect_{token}\n'
                             'Перешлите её владельцу аккаунта. Отключить доступ можно в /accounts.')
        elif cmd == "/web":
            url = self.mini_app_url()
            if not url.startswith('https://'):
                await self.reply('Адрес приложения ещё не настроен.')
                return
            token = web_login.issue_link(self.store, self.config.owner_id)
            link = url + ('' if url.endswith('/') else '/') + '#login=' + token
            await self.reply('🔑 Вход в календарь из браузера — телефон или компьютер.\n'
                             f'Ссылка одноразовая и действует 10 минут; вход сохранится на {web_login.session_seconds(url) // 86400} дней.\n'
                             'Никому её не пересылайте. Устройства видны в приложении: Ещё → Вход из браузера.',
                             reply_markup={'inline_keyboard': [[{'text': 'Открыть в браузере', 'url': link}]]})
        elif cmd == "/help":
            await self.reply(HELP, reply_markup=MENU)
        elif cmd == "/weather":
            await self.reply(await self.weather.today())
        elif cmd == "/next":
            events, notes = await self.schedule.upcoming(now)
            current = [e for e in events if e.start <= now]
            following = next((e for e in events if e.start > now), None)
            parts = ["▶️ Сейчас\n" + "\n".join(event_line(e) for e in current)] if current else []
            if following:
                mins = int((following.start - now).total_seconds() / 60)
                parts.append(f"⏭ Следующее · {following.start:%d.%m} · через {mins} мин\n" + event_line(following))
            await self.reply("\n\n".join(parts + notes) or "В ближайшие 7 дней занятий и планов нет.")
        elif cmd == "/free":
            tokens = args.split()
            day = parse_day(tokens[0], today) if tokens else today
            minutes = int(tokens[1]) if len(tokens) > 1 else 30
            if not 5 <= minutes <= 900:
                raise ValueError("Недопустимая длительность")
            events, note, _ = await self.schedule.day(day)
            slots = free_slots(events, day, tz, minutes, now if day == today else None)
            lines = [f"{a:%H:%M}–{b:%H:%M} · {int((b-a).total_seconds()/60)} мин" for a, b in slots]
            result = f"🕊 Окна на {day:%d.%m}, от {minutes} мин\n" + ("\n".join(lines) or "Подходящих окон нет.")
            await self.reply(result + ("\n" + note + "\nОкна могут быть заняты парами, которые не удалось проверить." if note else ""))
        elif cmd == "/sync":
            _, note, changed = await self.schedule.day(today, force=True)
            _, note2, changed2 = await self.schedule.day(today + timedelta(days=7), force=True)
            await self.reply(note or note2 or ("🔄 Расписание обновлено, есть изменения." if changed or changed2 else "✅ Расписание проверено."))
        elif cmd in ("/add", "/plan"):
            # Without arguments ChatUI.command has already opened the guided form.
            tokens = args.split(maxsplit=3 if cmd == "/plan" else 2)
            due = at(parse_day(tokens[0], today), clock(tokens[1]), tz)
            duration = int(tokens[2]) if cmd == "/plan" else 0
            if due <= now or (cmd == "/plan" and not 5 <= duration <= 1440):
                await self.reply("Укажите будущее время и длительность плана от 5 до 1440 минут.")
                return
            text,priority = priority_text(title(tokens[3] if cmd == "/plan" else tokens[2]))
            uid = self.store.add_item("event" if cmd == "/plan" else "task", text, due.isoformat(), duration,priority=priority)
            await self.reply(f"✅ Добавлено #{uid}: {text}\n{due:%d.%m.%Y %H:%M}")
            if cmd == "/plan":
                events, _, _ = await self.schedule.day(due.date())
                from .models import overlaps
                conflicts = [pair for pair in overlaps(events) if any(e.uid == f"plan:{uid}" for e in pair)]
                if conflicts:
                    await self.reply("⚠️ План пересекается с занятиями. Проверьте /day " + due.date().isoformat())
        elif cmd == "/hack":
            await self.hack(args)
        elif cmd == "/mail":
            await self.mail_command(args)
        elif cmd == "/reminders":
            # /tasks is served by ChatUI.task_list; only the reminder list remains here.
            projects = {p["id"]: p for p in self.store.projects()}
            items = self.store.items("reminder")
            if not items:
                await self.reply("Пока ничего нет. /add — дедлайн, /plan — план, /remind — напоминание.")
                return
            page = int(args) if args else 1
            pages = (len(items)+5)//6
            if not 1 <= page <= pages:
                raise ValueError("Страница не найдена")
            lines, buttons = [f"📋 Страница {page}/{pages}"], []
            for item in items[(page-1)*6:page*6]:
                due = datetime.fromisoformat(item["due"])
                if item["recurrence"] != "once":
                    future = [d for d in occurrences(item, today, today+timedelta(days=7)) if d >= now]
                    due = future[0] if future else due
                label = {"task": "🎯 Дедлайн", "event": "🗓 План", "reminder": "🔔 Напоминание"}[item["kind"]]
                if item["project"]:
                    label = "🏆 " + projects[item["project"]]["title"] + (" · дедлайн" if item["kind"] == "task" else " · событие")
                repeat = {"once": "", "daily": " · ежедневно", "weekly": " · еженедельно"}[item["recurrence"]]
                suffix = " · просрочено" if item["kind"] == "task" and due < now else ""
                lines.append(f"{label} #{item['id']}\n{item['title']}\n{due:%d.%m.%Y %H:%M}{repeat}{suffix}")
                buttons.append([{"text": f"✓ #{item['id']}", "callback_data": f"done:{item['id']}"},
                                {"text": f"#{item['id']} +1 час", "callback_data": f"snooze:{item['id']}"}])
            navigation = []
            if page > 1:
                navigation.append({"text": "← Назад", "callback_data": f"{cmd} {page-1}"})
            if page < pages:
                navigation.append({"text": "Дальше →", "callback_data": f"{cmd} {page+1}"})
            if navigation:
                buttons.append(navigation)
            await self.reply("\n\n".join(lines), reply_markup={"inline_keyboard": buttons})
        elif cmd == "/done":
            await self.reply("✅ Готово / отключено." if self.store.finish(int(args)) else "Активная запись не найдена.")
        elif cmd == "/move":
            uid, day, value = args.split()
            due = at(parse_day(day, today), clock(value), tz)
            if due <= now:
                raise ValueError("Дата в прошлом")
            await self.reply("✅ Перенесено." if self.store.move(int(uid), due.isoformat()) else "Активная запись не найдена.")
        elif cmd == "/remind":
            tokens = args.split()
            recurrence = tokens[0].lower()
            if recurrence == "daily":
                due = at(today, clock(tokens[1]), tz)
                if due <= now:
                    due += timedelta(days=1)
                text = title(" ".join(tokens[2:]))
            elif recurrence == "weekly":
                weekday = DAY_CODES[tokens[1].lower()]
                due = at(today + timedelta(days=(weekday - today.weekday()) % 7), clock(tokens[2]), tz)
                if due <= now:
                    due += timedelta(days=7)
                text = title(" ".join(tokens[3:]))
            else:
                due = at(parse_day(tokens[0], today), clock(tokens[1]), tz)
                recurrence, text = "once", title(" ".join(tokens[2:]))
                if due <= now:
                    raise ValueError("Дата в прошлом")
            uid = self.store.add_item("reminder", text, due.isoformat(), recurrence=recurrence)
            await self.reply(f"🔔 Напоминание #{uid} сохранено. Первое: {due:%d.%m.%Y %H:%M}")
        elif cmd == "/focus":
            tokens = args.split(maxsplit=1)
            minutes = int(tokens[0]) if tokens else 25
            if not 1 <= minutes <= 180:
                raise ValueError("Недопустимый таймер")
            text = title(tokens[1]) if len(tokens) > 1 else "Фокус-сессия"
            uid = self.store.add_item("reminder", "Фокус завершён: " + text,
                                      (now + timedelta(minutes=minutes)).isoformat())
            await self.reply(f"🍅 Фокус на {minutes} мин запущен · #{uid}. Напомню сделать перерыв.")
        elif cmd == "/lesson":
            await self.lesson(args)
        elif cmd in ("/skip", "/unskip"):
            day, uid = args.split()
            day = parse_day(day, today)
            if uid not in {r["id"] for r in self.store.rules()}:
                await self.reply("Такого правила нет. Список: /lesson list")
                return
            self.store.skip(uid, day.isoformat(), cmd == "/skip")
            await self.reply("✅ Исключение сохранено." if cmd == "/skip" else "✅ Исключение убрано.")
        elif cmd == "/settings":
            fields = [("Группа", self.store.get("group_name")), ("Сводки", self.store.get("digest_times")),
                      ("Погода", self.store.get("weather_times")), ("Завтра", self.store.get("evening_time")),
                      ("За минут до занятий", self.store.get("alert_minutes")),
                      ("Обновление сайта, мин", self.store.get("sync_minutes")),
                      ("Уведомления", self.store.get("notifications") and self.store.get("subscribed"))]
            await self.reply("⚙️ Настройки\n" + "\n".join(f"{k}: {v}" for k, v in fields)
                             + "\n\n/set digest 07:30,13:00\n/set weather 08:00\n/set evening 21:00\n"
                             "/set alerts 30,10\n/set sync 180\nДля отключения укажите off.\n"
                             "/pause — выключить все уведомления; /resume — включить.",
                             reply_markup={"inline_keyboard": [[{"text": "Пауза", "callback_data": "/pause"},
                                                                  {"text": "Включить", "callback_data": "/resume"}]]})
        elif cmd == "/set":
            await self.setting(args)
        elif cmd == "/group":
            if args not in ("1", "2"):
                raise ValueError("Подгруппа 1 или 2")
            self.store.set("group_id", int(args))
            self.store.set("group_name", "Группа " + args)
            self.store.set("pending_change", None)
            await self.reply("✅ Группа: Группа " + args)
        elif cmd in ("/pause", "/resume", "/stop"):
            self.store.set("notifications", cmd == "/resume")
            if cmd == "/stop":
                self.store.set("subscribed", False)
            elif cmd == "/resume":
                self.store.set("subscribed", True)
            await self.reply("🔔 Уведомления включены." if cmd == "/resume" else "🔕 Автоматические сообщения выключены.")
        else:
            await self.reply("Выберите кнопку или команду /help", reply_markup=MENU)

    async def hack(self, args):
        now, tz = self.now(), self.config.timezone
        if not args:
            text, markup = hackathons.overview_text(self.store, now)
            await self.reply(text, **({"reply_markup": markup} if markup else {}))
            return
        uid, _, rest = args.partition(" ")
        action, _, rest = rest.strip().partition(" ")
        rest = rest.strip()
        if uid == "new":
            uid, name = action, rest
            if not hackathons.PROJECT_ID.fullmatch(uid) or self.store.project(uid):
                await self.reply("ID: 2–24 символа латиницей, цифры или дефис, без повторов.\n"
                                 "Пример: /hack new alfa Alfa-Hack 2026")
                return
            name = title(name)
            self.store.put_project(dict(id=uid, title=name, kind="hackathon", organizer="", status="registration",
                                        role="", summary="", prize="", links=[]))
            await self.reply(f"🏆 Добавлен «{name}».\nЭтапы: /hack {uid} task 2026-11-16 14:00 Сдать решение")
            return
        project = self.store.project(uid)
        if not project:
            await self.reply("Хакатон не найден. Список: /hack")
            return
        if not action:
            await self.show_card(uid)
        elif action == "status":
            if rest not in hackathons.STATUSES:
                raise ValueError("Неизвестный статус")
            project["status"] = rest
            self.store.put_project(project)
            await self.reply(f"✅ {project['title']}: {hackathons.STATUSES[rest]}")
        elif action == "link":
            url, _, name = rest.partition(" ")
            if not url.startswith(("https://", "http://")) or len(url) > 500 or len(project["links"]) >= 8:
                raise ValueError("Нужна ссылка http(s), не больше восьми")
            project["links"].append(dict(title=title(name or "Ссылка"), url=url))
            self.store.put_project(project)
            await self.reply("🔗 Ссылка сохранена.")
        elif action in ("task", "event", "day"):
            tokens = rest.split(maxsplit={"task": 2, "event": 3, "day": 1}[action])
            if action == "day":
                due, duration, text = at(parse_day(tokens[0], now.date()), "00:00", tz), 1440, title(tokens[1])
            else:
                due = at(parse_day(tokens[0], now.date()), clock(tokens[1]), tz)
                duration = int(tokens[2]) if action == "event" else 0
                text = title(tokens[3] if action == "event" else tokens[2])
                if action == "event" and not 5 <= duration <= 1440:
                    raise ValueError("Недопустимая длительность")
            stage = self.store.add_item("task" if action == "task" else "event", text, due.isoformat(), duration,
                                        project=uid, all_day=action == "day")
            await self.reply(f"✅ Этап #{stage} добавлен в «{project['title']}»: {text}")
        else:
            raise ValueError("Неизвестное действие")

    async def mail_command(self, args):
        action, _, value = args.partition(" ")
        action = action.lower()
        if action in ("", "status"):
            await self.reply(self.mail.status(self.now()))
        elif action == "check":
            if not self.mail.configured:
                await self.reply(self.mail.status(self.now()))
            elif await self.mail.check(self.now(), manual=True) == 0:
                await self.reply("📬 Новых писем для пересылки нет.")
        elif action in ('all', 'important','opportunities'):
            self.store.set('mail_mode', action)
            self.mail.next_check = None
            await self.reply('🚨 Режим: отборы, хакатоны и обучение; краткие письма с добавлением задач.' if action=='opportunities' else '📬 Режим: все новые входящие, включая рассылки и уведомления.' if action == 'all'
                             else '📬 Режим: только важные письма.')
        elif action in ("on", "off"):
            self.store.set("mail_enabled", action == "on")
            self.mail.next_check = None
            await self.reply("📬 Пересылка писем включена." if action == "on" else
                             "📭 Письма в чат больше не присылаю. Включить: /mail on")
        elif action in ("vip", "mute", "unvip", "unmute"):
            entry = normalize(value)
            key, other = ("mail_vip", "mail_mute") if action.endswith("vip") else ("mail_mute", "mail_vip")
            entries = set(self.store.get(key, []))
            if action.startswith("un"):
                entries.discard(entry)
            else:
                entries.add(entry)
                self.store.set(other, sorted(set(self.store.get(other, [])) - {entry}))
            self.store.set(key, sorted(entries))
            await self.reply({"vip": f"⭐ Письма от {entry} присылаю всегда.",
                              "mute": f"🔕 Письма от {entry} больше не присылаю. Вернуть: /mail unmute {entry}",
                              "unvip": f"✅ {entry} убран из важных.", "unmute": f"✅ {entry} снова может приходить."}[action])
        else:
            raise ValueError("Неизвестное действие")

    async def show_card(self, uid, message=None):
        text, markup = hackathons.card(self.store, uid, self.now())
        if message:
            try:
                await self.telegram.call("editMessageText", chat_id=message["chat"]["id"],
                                         message_id=message["message_id"], text=text, reply_markup=markup,
                                         link_preview_options={"is_disabled": True})
                return
            except ServiceError as exc:
                if exc.status != 400:  # 400: message too old or unchanged; a fresh card is fine.
                    raise
        await self.reply(text, reply_markup=markup)

    async def hack_callback(self, data, message):
        _, action, *rest = data.split(":")
        if action == "list":
            text, markup = hackathons.overview_text(self.store, self.now())
            await self.reply(text, **({"reply_markup": markup} if markup else {}))
        elif action == "open":
            if not self.store.project(rest[0]):
                raise KeyError(rest[0])
            await self.show_card(rest[0])
        elif action == "check":
            item = next(i for i in self.store.items(include_done=True) if i["id"] == int(rest[0]) and i["project"])
            hackathons.set_done(self.store, item, not hackathons.is_done(self.store, item))
            await self.show_card(item["project"], message)
        elif action == "status":
            project = self.store.project(rest[0])
            if not project or rest[1] not in hackathons.STATUSES:
                raise KeyError(rest[0])
            project["status"] = rest[1]
            self.store.put_project(project)
            await self.show_card(project["id"], message)

    async def lesson(self, args):
        action, _, rest = args.partition(" ")
        if action == "list":
            lines = []
            for rule in self.store.rules():
                days = ", ".join(WEEKDAYS[d] for d in rule["weekdays"])
                lines.append(f"{rule['id']} · {days} {rule['time']} · {rule['duration_minutes']} мин · "
                             f"{rule['cycle'].upper()}\n{rule['title']}")
            await self.reply("📚 Правила занятий\n\n" + "\n\n".join(lines))
        elif action == "delete":
            await self.reply("✅ Правило удалено." if self.store.delete_rule(rest.strip()) else "Правило не найдено.")
        elif action == "add":
            days, value, duration, cycle, text = rest.split(maxsplit=4)
            weekdays = sorted({DAY_CODES[d.lower()] for d in days.split(",")})
            duration = int(duration)
            if not 5 <= duration <= 1440 or cycle.lower() not in ("all", "a", "b"):
                raise ValueError("Неверная длительность или цикл")
            uid = "custom-" + uuid4().hex[:8]
            self.store.put_rule(dict(id=uid, weekdays=weekdays, time=clock(value), duration_minutes=duration,
                                     cycle=cycle.lower(), title=title(text)))
            await self.reply("✅ Правило добавлено: " + uid)
        else:
            await self.reply("/lesson list\n/lesson add mon,wed 17:00 120 all Моё занятие\n/lesson delete ID")

    async def setting(self, args):
        name, value = args.split(maxsplit=1)
        if name in ("digest", "weather"):
            values = [] if value == "off" else sorted({clock(v.strip()) for v in value.split(",")})
            if len(values) > 6:
                raise ValueError("Не более 6 отправок в день")
            self.store.set(name + "_times", values)
        elif name == "evening":
            self.store.set("evening_time", None if value == "off" else clock(value))
        elif name == "alerts":
            values = [] if value == "off" else sorted({int(v.strip()) for v in value.split(",")}, reverse=True)
            if len(values) > 5 or any(v < 1 or v > 1440 for v in values):
                raise ValueError("От 1 до 1440 минут, до 5 интервалов")
            self.store.set("alert_minutes", values)
        elif name == "sync":
            minutes = int(value)
            if not 15 <= minutes <= 1440:
                raise ValueError("От 15 до 1440 минут")
            self.store.set("sync_minutes", minutes)
            self.scheduler.next_sync = None
        elif name == "mail":
            minutes = int(value)
            if not 1 <= minutes <= 60:
                raise ValueError("От 1 до 60 минут")
            self.store.set("mail_minutes", minutes)
            self.mail.next_check = None
        elif name == "anchor":
            anchor = date.fromisoformat(value)
            if anchor.weekday() != 0:
                raise ValueError("Нужен понедельник")
            self.store.set("cycle_anchor", value)
        else:
            raise ValueError("Неизвестная настройка")
        await self.reply("✅ Настройка сохранена.")

    async def profile(self):
        mode = "Отдельный профиль" if self.config.public_mode else "Личный календарь"
        extra = "/settings — уведомления и настройки" if self.config.public_mode else "/accounts — доступ к личному календарю"
        await self.reply(
            f"👤 МОЙ ПРОФИЛЬ\n\n{mode}\nTelegram ID · {self.config.owner_id}\n"
            f"Группа · {self.store.get('group_name') or 'не выбрана'}\n"
            f"Часовой пояс · {self.config.timezone}\n\n"
            f"/app — открыть приложение\n{extra}"
        )

    def startup_accounts(self):
        return allowed_ids(self.store, self.config.owner_id)

    async def run_notifications(self):
        await self.scheduler.run()

    async def run(self):
        while True:
            try:
                identity = await self.telegram.call("getMe")
                break
            except ServiceError as exc:
                if exc.status == 401:
                    raise ValueError('Проверьте BOT_TOKEN') from None
                log.warning('Telegram недоступен при запуске; Mini App продолжает работать. Повтор через 30 с.')
                await asyncio.sleep(30)
        webhook = await self.telegram.call("getWebhookInfo")
        if webhook.get("url"):
            raise ValueError("У бота установлен webhook. Для перехода на polling запустите --delete-webhook.")
        self.store.set('bot_username', identity['username'])
        log.info("Бот @%s запущен; OWNER_ID %s", identity["username"], "настроен" if self.config.owner_id else "не настроен")
        await self.telegram.call("setMyCommands", commands=[
            {"command": name, "description": desc} for name, desc in
            [("menu", "Меню бота"), ("profile", "Мой профиль"), ("zp", "Зарплата: проведено, заработано, прогноз"), ("students", "Ученики, даты занятий и суммы за месяц"),
             ("lesson", "Добавление и перенос занятия в чате"), ("calendar", "Расписание: выбрать день"),
             ("import", "Импорт из Google и Apple Calendar"), ("add", "Быстро добавить задачу"),
             ("reconcile", "Сверить занятия и оплату Reollity"),
             ("accounts", "Подключённые аккаунты"),
             ("pay", "Оплата ученика по имени или фамилии"),
             ("week", "Недельное расписание"), ("month", "Календарь месяца"), ("cancel", "Отменить ввод"),
             ("plan", "Добавить план"), ("focus", "Таймер фокуса"), ("stats", "Прогресс недели"),
             ("app", "Открыть приложение"), ("web", "Войти из браузера"), ("invite", "Пригласить второй аккаунт"), ("today", "План на сегодня"), ("tomorrow", "План на завтра"), ("next", "Следующее занятие"),
             ("tasks", "Задачи и планы"), ("hack", "Хакатоны и этапы"), ("mail", "Важная почта"), ("weather", "Прогноз погоды"),
             ("gym", "Зал, программы и журнал тренировок"), ("food", "Питание и вода"), ("kcal", "Посчитать калории и БЖУ по сообщению"), ("recipes", "Рецепты и мои ссылки"), ("steps", "Шаги за день"), ("activity", "Бег, зал и другая активность"), ("weight", "Вес и рост для расчёта расхода"), ("sleep", "Дневник сна"),
             ("ai", "ИИ-помощник для задач и планов"),
             ("settings", "Настройки"), ("help", "Все команды"), ("id", "Мой Telegram ID")]
            if not self.config.public_mode or name not in {"web", "invite", "accounts", "mail", "reconcile"}])
        for uid in self.startup_accounts():
            self.background(self.bind_app_menu(uid))
        worker = asyncio.create_task(self.run_notifications())
        backoff = 1
        try:
            while True:
                try:
                    updates = await self.telegram.call("getUpdates", offset=self.store.get("offset", 0),
                                                        timeout=30, allowed_updates=["message", "callback_query"])
                    HEARTBEAT.polled()
                    backoff = 1
                    for update in updates:
                        # Persist acceptance before effects: a failed reply must not create a task twice.
                        # A crash during handling can lose this one command; the user can safely retry.
                        self.store.set("offset", update["update_id"] + 1)
                        try:
                            await self.handle(update)
                        except ServiceError:
                            raise
                        except Exception as exc:
                            # The traceback goes through logsafe, which strips tokens and keys.
                            log.exception("Не обработана команда: %s", type(exc).__name__)
                            # Advance past a malformed/unsupported update to avoid a poison-message loop.
                except ServiceError as exc:
                    if exc.status in (401, 409):
                        raise ValueError("Проверьте BOT_TOKEN и убедитесь, что запущен только один экземпляр.") from None
                    delay = min(60, max(backoff, exc.retry_after))
                    log.warning("Telegram недоступен; повтор через %s с", delay)
                    await asyncio.sleep(delay)
                    backoff = min(backoff * 2, 30)
        finally:
            worker.cancel()
            for task in list(self._background_tasks):task.cancel()
            if self._background_tasks:
                await asyncio.gather(*list(self._background_tasks),return_exceptions=True)
            try:
                await worker
            except asyncio.CancelledError:
                pass
