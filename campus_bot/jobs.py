import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .models import at
from .network import ServiceError

log = logging.getLogger(__name__)


def occurrences(item, first_day, last_day):
    due = datetime.fromisoformat(item["due"])
    recurrence = item["recurrence"]
    if recurrence == "once":
        return [due] if first_day <= due.date() <= last_day else []
    result = []
    day = max(first_day, due.date())
    while day <= last_day:
        if recurrence == "daily" or (recurrence == "weekly" and day.weekday() == due.weekday()):
            result.append(datetime.combine(day, due.timetz()))
        day += timedelta(days=1)
    return result


@dataclass(frozen=True)
class Job:
    key: str
    due: datetime
    text: str


def notification_jobs(now, events, items, alert_minutes, projects=None):
    jobs, projects = [], projects or {}
    for event in events:
        if event.cancelled or event.all_day or event.start <= now:
            continue
        for lead in alert_minutes:
            due = event.start - timedelta(minutes=lead)
            jobs.append(Job(f"event:{event.uid}:{event.start.isoformat()}:{lead}", due,
                            f"⏰ Через {lead} мин · {event.time_label}\n{event.title}\n{event.details}"))
    for item in items:
        if item["kind"] == "task":
            if item.get('all_day') or item.get('is_group') or item.get('skipped'):
                continue
            if item.get('plan_id') and item.get('duration'):
                end=datetime.fromisoformat(item['due'])
                start=end-timedelta(minutes=item['duration'])
                for lead in alert_minutes:
                    jobs.append(Job(f'plan-task:{item["id"]}:{start.isoformat()}:{lead}',start-timedelta(minutes=lead),
                                    f'⏰ Через {lead} мин · {start:%H:%M}–{end:%H:%M}\n{item["title"]}'))
                continue
            project = projects.get(item.get("project"))
            if item.get("project") and (not project or project.get("status") in ("done", "dropped")):
                continue
            due = datetime.fromisoformat(item["due"])
            # Hackathon deadlines need time to organise a team, so they start three days ahead.
            for hours in (72,24,6,2,0) if item.get('priority') else (72, 24, 2, 0) if project else (24, 2, 0):
                when = due - timedelta(hours=hours)
                label = f"через {hours} ч" if hours else "сейчас"
                head = f"🏆 {project['title']} · дедлайн {label}" if project else f"🎯 Дедлайн {label}"
                if item.get('priority'):head='🚨 ВАЖНО · '+head
                note = "\n" + item["note"] if item.get("note") else ""
                jobs.append(Job(f"task:{item['id']}:{due.isoformat()}:{hours}", when,
                                f"{head} · #{item['id']}\n{item['title']}\n{due:%d.%m %H:%M}{note}"))
        elif item["kind"] == "reminder":
            for due in occurrences(item, now.date() - timedelta(days=1), now.date()):
                jobs.append(Job(f"reminder:{item['id']}:{due.isoformat()}", due,
                                f"🔔 Напоминание · #{item['id']}\n{item['title']}"))
    return jobs


WEATHER_REFRESH = timedelta(minutes=30)


class Scheduler:
    def __init__(self, bot):
        self.bot = bot
        self.next_sync = None
        self.next_weather = None
        self.weather_day = None
        self.retry_at = {}
        self.jobs = {}
        self.reader = None

    def spawn(self, name, make):
        """Run a slow refresh in the background, at most one of each kind at a time."""
        running = self.jobs.get(name)
        if running and not running.done():
            return running
        self.jobs[name] = self.bot.background(make())
        return self.jobs[name]

    def cached_schedule(self):
        """Reminders read the timetable from cache (up to 12 h old) and never wait for the website."""
        if self.reader is None:
            from .schedule import Schedule
            main = self.bot.schedule
            self.reader = Schedule(self.bot.store, self.bot.config, fetch=main.fetch, cache_first=True, retry_after=main.retry_after)
            # One lock for both: with an empty cache the reader waits for the running sync instead of fetching again.
            self.reader.lock = main.lock
        return self.reader

    async def sync(self, today):
        """Fetch today and tomorrow from the university site; a change is noticed on the next tick."""
        for day in (today, today + timedelta(days=1)):
            await self.bot.schedule.day(day, force=True)

    def warm_caches(self, now, force_sync):
        """Background refreshes the Mini App reads from cache, never awaited by the tick."""
        bot = self.bot
        if force_sync:
            bot.background(bot.schedule.prefetch(now.date()))
        # A new day has an empty weather cache: refresh right after midnight too.
        if self.next_weather is None or now >= self.next_weather or now.date() != self.weather_day:
            self.next_weather, self.weather_day = now + WEATHER_REFRESH, now.date()
            bot.background(bot.weather.today(now))

    async def deliver(self, key, due, now, make_text, grace=10):
        store = self.bot.store
        if not timedelta(0) <= now - due <= timedelta(minutes=grace):
            return
        if store.delivered(key) or now < self.retry_at.get(key, now):
            return
        try:
            text = await make_text()
            if text is None:  # nothing to remind about today: mark it so the check is not repeated
                store.mark(key, now.isoformat())
                return
            text, extra = text if isinstance(text, tuple) else (text, {})
            await self.bot.notify(text,delivery_key=key,**extra)
            store.mark(key, now.isoformat())
            self.retry_at.pop(key, None)
        except ServiceError as exc:
            self.retry_at[key] = now + timedelta(seconds=max(60, exc.retry_after))
            if exc.status == 403:
                store.set("subscribed", False)
            log.warning("Доставка не выполнена: %s", exc)

    async def tick(self, now=None):
        bot, store = self.bot, self.bot.store
        now = now or datetime.now(bot.config.timezone)
        if bot.config.owner_id and bot.reollity.configured:
            # Reollity can take a minute or more; reminders must not wait for it.
            self.spawn("reollity", lambda: bot.reollity.refresh(now))
        if not store.get("subscribed") or not store.get("notifications") or not bot.config.owner_id:
            return
        force = self.next_sync is None or now >= self.next_sync
        if force:
            self.next_sync = now + timedelta(minutes=store.get("sync_minutes"))
            self.spawn("sync", lambda: self.sync(now.date()))
        reader = self.cached_schedule()
        today, note, _ = await reader.day(now.date())
        tomorrow, note2, _ = await reader.day(now.date() + timedelta(days=1))
        self.warm_caches(now, force)
        if store.get("pending_change"):
            group = store.get("pending_change")
            async def change_text():
                return f"🔄 Изменилось расписание {group}.\n" + await bot.day_text(now.date(), weather=False)
            # Stable across retries until successfully delivered.
            key = "change:" + str(store.get("change_sequence", 0))
            await self.deliver(key, now, now, change_text)
            if store.delivered(key):
                store.set("pending_change", None)
                store.set("change_sequence", store.get("change_sequence", 0) + 1)
        for clock in store.get("digest_times"):
            await self.deliver(f"digest:{now.date()}:{clock}", at(now.date(), clock, bot.config.timezone), now,
                               lambda: bot.day_text(now.date()), grace=30)
        for clock in store.get("weather_times"):
            await self.deliver(f"weather:{now.date()}:{clock}", at(now.date(), clock, bot.config.timezone), now,
                               lambda: bot.weather.today(now), grace=30)
        evening = store.get("evening_time")
        gym_settings = store.get("wellness_settings", {}) or {}
        gym = gym_settings.get("remind_time")
        # Only on chosen weekdays, so adding today later still brings today's reminder.
        if gym and now.weekday() in (gym_settings.get("remind_days") or []):
            from .wellness_chat import reminder
            async def gym_text():
                return reminder(bot, now)
            await self.deliver(f"gym:{now.date()}", at(now.date(), gym, bot.config.timezone), now, gym_text, grace=30)
        if now.day == 1 and store.get('tutoring_monthly_report', True):
            previous = now.date().replace(day=1)-timedelta(days=1)
            async def monthly_text():
                if store.get('reollity_sync'):
                    from .reollity import billing_state
                    from .tutoring import money
                    report = billing_state(store,bot.schedule,now.date().replace(day=1))
                    rows = [f'💳 ПРЕДОПЛАТА · {now:%m.%Y}',
                            'Занятия месяца + прошлый долг − аванс − уже внесённое.']
                    rows += [r['name']+' → '+money(r['due']) for r in report['students'] if r['due']]
                    rows += ['К внесению всего: '+money(report['total_due']),
                             '/students — выбрать ученика и посмотреть расчёт, даты и оплаты.']
                    return '\n\n'.join(rows)
                return bot.tutoring.book.summary(previous.replace(day=1))
            await self.deliver(f'tutoring-month:{previous:%Y-%m}', at(now.date(), '10:00', bot.config.timezone),
                               now, monthly_text, grace=12*60)
        if store.get('salary_daily_report',False):
            from .salary_chat import daily as salary_daily
            await salary_daily(bot,now)
        if evening:
            await self.deliver(f"evening:{now.date()}:{evening}", at(now.date(), evening, bot.config.timezone), now,
                               lambda: bot.day_text(now.date() + timedelta(days=1), weather=False), grace=30)
        unique = {(e.uid, e.start): e for e in today + tomorrow
                  if not store.checked(e.uid+'|'+e.start.date().isoformat())}
        projects = {p["id"]: p for p in store.projects()}
        for job in notification_jobs(now, list(unique.values()), store.items(), store.get("alert_minutes"), projects):
            async def text_for(job=job):
                return job.text + ("\n⚠️ Расписание вуза из кэша; проверьте сайт." if
                                   job.key.startswith("event:uni:") and (note or note2) else "")
            await self.deliver(job.key, job.due, now, text_for)
            if job.key.startswith("reminder:") and store.delivered(job.key):
                uid = int(job.key.split(":")[1])
                item = next((i for i in store.items("reminder") if i["id"] == uid), None)
                if item and item["recurrence"] == "once":
                    store.finish(uid)
        if bot.mail.due(now):
            await bot.mail.check(now)

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception as exc:
                # Full traceback; logsafe removes tokens and keys from it.
                log.exception("Ошибка планировщика: %s", type(exc).__name__)
            await asyncio.sleep(20)
