import asyncio
from datetime import date, datetime, timedelta
import hashlib
import json
from dataclasses import replace
from urllib.parse import urlencode

from .models import Event, at
from .network import ServiceError, get_json

API_BASE = "https://api.cube.nlabs.su/api"


def personal_events(day, rules, anchor, tz, skipped=lambda uid, day: False):
    cycle = "a" if ((day - anchor).days // 7) % 2 == 0 else "b"
    events = []
    for rule in rules:
        repeat=rule.get('cycle','all')
        if rule.get('start_date') and day < date.fromisoformat(rule['start_date']):
            continue
        if rule.get('end_date') and day > date.fromisoformat(rule['end_date']):
            continue
        if repeat=='once':
            if day != date.fromisoformat(rule['date']):
                continue
        elif day < anchor or (repeat=='weekdays' and day.weekday()>4) or (
                repeat not in ('daily','weekdays') and day.weekday() not in rule['weekdays']):
            continue
        if repeat not in ('once','daily','weekdays','all',cycle):
            continue
        start = at(day, rule["time"], tz)
        events.append(Event(
            "personal:" + rule["id"], rule["title"], start,
            start + timedelta(minutes=rule["duration_minutes"]), "personal",
            rule.get('note',''), skipped(rule["id"], day.isoformat()),
        ))
    return events


def parse_university(payload, tz, group_id):
    if not isinstance(payload, dict) or payload.get("status") not in ("AVAILABLE", "EMPTY"):
        raise ValueError("Расписание не опубликовано или изменился формат ответа")
    if not isinstance(payload.get("data"), list):
        raise ValueError("В ответе нет списка занятий")
    events = []
    for row in payload["data"]:
        if not any(g["id"] == group_id for g in row.get("groups", [])):
            raise ValueError("Источник вернул занятие другой группы")
        day = date.fromisoformat(row["date"])
        kind = row.get("type") or {}
        discipline = row.get("discipline") or {}
        all_day = bool(kind.get("all_day"))
        if all_day:
            start, end = at(day, "00:00", tz), at(day + timedelta(days=1), "00:00", tz)
        else:
            if not row.get("start_time") or not row.get("end_time"):
                raise ValueError("У занятия отсутствует время")
            start, end = at(day, row["start_time"], tz), at(day, row["end_time"], tz)
            if end <= start:
                raise ValueError("Неверный интервал занятия")
        title = discipline.get("name") or kind.get("name") or "Занятие"
        details = [kind.get("short_name") or kind.get("name")]
        place = row.get("place")
        if place:
            details.append("ауд. " + place["name"])
        details.extend(t["short_name"] for t in row.get("teachers", []))
        if row.get("is_remotely"):
            details.append("дистанционно")
        events.append(Event("uni:" + str(row["id"]), title, start, end, "university",
                            " · ".join(d for d in details if d), row.get("status") == 3, all_day))
    return events


def fingerprint(events):
    data = sorted((e.uid, e.title, e.start.isoformat(), e.end.isoformat(), e.details, e.cancelled)
                  for e in events)
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def extra_university_events(rows, day, tz, group_id):
    """One-off announcements supplied by the owner, independent of website refreshes."""
    events = []
    for row in rows:
        if row['group_id'] != group_id:
            continue
        start = datetime.fromisoformat(row['start'])
        start = start.replace(tzinfo=tz) if start.tzinfo is None else start.astimezone(tz)
        if start.date() != day:
            continue
        end = datetime.fromisoformat(row['end']) if row.get('end') else start
        end = end.replace(tzinfo=tz) if end.tzinfo is None else end.astimezone(tz)
        if end < start:
            raise ValueError('Окончание события раньше начала')
        details = row.get('details', '')
        if end == start:
            details += ' · окончание не указано'
        events.append(Event('uni-extra:' + row['id'], row['title'], start, end,
                            'university', details.strip(' ·')))
    return events


# The Mini App answers from cache up to this age; the bot's scheduler keeps the
# coming weeks fresher than that, so app requests never wait for the website.
CACHE_FIRST_MAX_AGE = timedelta(hours=12)
PREFETCH_WEEKS = 4
# A cache-first answer older than this carries a warning.
STALE_AFTER = timedelta(hours=1)


class Schedule:
    def __init__(self, store, config, fetch=None, cache_first=False, retry_after=None, *, parallel_weeks=False):
        self.store, self.config = store, config
        self.fetch = fetch or (self.fetch_for_app if cache_first else get_json)
        doc = json.loads(config.lessons_path.read_text(encoding="utf-8"))
        self.anchor = date.fromisoformat(doc["cycle_anchor"])
        if self.anchor.weekday() != 0:
            raise ValueError("Начало двухнедельного цикла должно быть понедельником")
        store.seed_rules(doc)
        self.lock = asyncio.Lock()
        self.week_locks = {} if parallel_weeks else None
        self.cache_first = cache_first
        # Shared by the Mini App's per-request instances, so a website outage is
        # retried every five minutes instead of on every request.
        self.retry_after = {} if retry_after is None else retry_after

    @staticmethod
    async def fetch_for_app(url, service):
        # Use the socket deadline so asyncio.run does not wait for a timed-out
        # executor thread after the HTTP handler has prepared its response.
        return await get_json(url, service, timeout=3)

    def fresh(self, cached, now, force):
        if not cached or force:
            return False
        age = now - datetime.fromisoformat(cached[1])
        ttl = timedelta(minutes=self.store.get("sync_minutes"))
        return age < (max(ttl, CACHE_FIRST_MAX_AGE) if self.cache_first else ttl)

    async def prefetch(self, today, weeks=PREFETCH_WEEKS):
        """Refresh the following weeks in the background for the Mini App."""
        for offset in range(1, weeks + 1):
            await self.university(today + timedelta(weeks=offset), force=True)

    def stale_note(self, cached, now):
        """A warning when a cache-first answer is much older than the normal refresh interval."""
        if not self.cache_first:
            return ''
        saved = datetime.fromisoformat(cached[1])
        ttl = timedelta(minutes=self.store.get("sync_minutes"))
        if now - saved < max(2 * ttl, STALE_AFTER):
            return ''
        return ("⚠️ Расписание вуза из кэша от " + saved.astimezone(self.config.timezone).strftime("%d.%m %H:%M")
                + "; сайт давно не обновлялся, проверьте изменения.")

    def fallback(self, cached, group_id):
        if cached:
            return parse_university(cached[0], self.config.timezone, group_id), (
                "⚠️ Сайт недоступен. Расписание из кэша от "
                + datetime.fromisoformat(cached[1]).strftime("%d.%m %H:%M")
                + "; проверьте изменения на сайте."), False
        return [], "⚠️ Не удалось получить расписание вуза. Это не означает, что пар нет.", False

    async def university(self, day: date, force=False):
        monday = day - timedelta(days=day.weekday())
        group_id = self.store.get("group_id")
        if not group_id:
            return [], '', False
        key = f"uni:{group_id}:{monday}"
        now = datetime.now(self.config.timezone)
        # A healthy cached answer must not wait for an unrelated slow forced refresh.
        cached = self.store.cache_get(key)
        if self.fresh(cached, now, force):
            return parse_university(cached[0],self.config.timezone,group_id),self.stale_note(cached, now),False
        lock = self.lock if self.week_locks is None else self.week_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self.store.cache_get(key)
            if self.fresh(cached, now, force):
                return parse_university(cached[0], self.config.timezone, group_id), self.stale_note(cached, now), False
            if not force and now < self.retry_after.get(key, now):
                return self.fallback(cached, group_id)
            query = urlencode({"group": group_id, "start_date": monday.isoformat(),
                               "end_date": (monday + timedelta(days=6)).isoformat()})
            try:
                payload = await self.fetch(API_BASE + "/timetable/lessons/viewer?" + query, "Расписание вуза")
                events = parse_university(payload, self.config.timezone, group_id)
                if any(not monday <= e.start.date() <= monday + timedelta(days=6) for e in events):
                    raise ValueError("Источник вернул другой диапазон дат")
                changed = cached is not None and fingerprint(events) != fingerprint(
                    parse_university(cached[0], self.config.timezone, group_id))
                self.store.cache_put(key, payload, now.isoformat())
                self.retry_after.pop(key, None)
                if changed:
                    self.store.set("pending_change", self.store.get("group_name"))
                return events, "", changed
            except (ServiceError, ValueError, KeyError, TypeError):
                self.retry_after[key] = now + timedelta(minutes=5)
                return self.fallback(cached, group_id)

    async def day(self, day: date, force=False, *, week=None):
        university, note, changed = week if week is not None else await self.university(day, force)
        result = [e for e in university if e.start.date() == day]
        for extra in extra_university_events(self.store.get('university_extras', []), day,
                                             self.config.timezone, self.store.get('group_id')):
            # The notice may describe the same scheduled class. Show the confirmed
            # colloquium once, using its announced start and not a guessed duration.
            discipline = extra.title.removeprefix('Коллоквиум · ').casefold()
            result = [e for e in result if not (e.start == extra.start and e.title.casefold() == discipline)]
            result.append(extra)
        result += self.personal(day)
        projects = {p["id"]: p for p in self.store.projects()}
        for item in self.store.items("event"):
            project = projects.get(item["project"])
            if item["project"] and (not project or project.get("status") == "dropped"):
                continue
            start = datetime.fromisoformat(item["due"])
            end = start + timedelta(minutes=item["duration"])
            # Include events crossing midnight in both days.
            if start.date() <= day <= (end - timedelta(microseconds=1)).date():
                result.append(Event("plan:" + str(item["id"]), item["title"], start, end,
                                    "hackathon" if project else "plan", project["title"] if project else item.get('note',''),
                                    all_day=bool(item["all_day"])))
        adjusted = []
        for event in result:
            if event.source == 'personal':
                adjusted.append(event)
                continue
            patch = self.store.override(event.uid + '|' + event.start.date().isoformat())
            if patch:
                event = replace(event, title=patch['title'], start=datetime.fromisoformat(patch['start']),
                                end=datetime.fromisoformat(patch['end']), cancelled=patch.get('cancelled', False), all_day=False,
                                details=event.details + ' · личная правка')
            adjusted.append(event)
        if any(not e.cancelled and not e.all_day and e.start == e.end for e in adjusted):
            note = '\n'.join(filter(None, [note, 'ℹ️ У коллоквиума указано только начало. '
                                          'Свободные окна после него не рассчитываются.']))
        return sorted(adjusted, key=lambda e: (e.start, e.title)), note, changed

    def personal(self, day, rules=None):
        """The same private lessons for calendar, monthly billing and chat edits; no university fetch."""
        anchor = date.fromisoformat(self.store.get('cycle_anchor', self.anchor.isoformat()))
        moved = {c['source_key']: c for c in self.store.lesson_changes()
                 if c.get('active') and c.get('source_key')}
        rules = self.store.rules() if rules is None else rules
        by_id = {r['id']: r for r in rules}
        base = personal_events(day, rules, anchor, self.config.timezone, self.store.skipped)
        sync = self.store.get('reollity_sync', {})
        if sync.get('first', '9999') <= str(day) < sync.get('cutoff', '0000'):
            from .tutoring import people, person_key
            covered = set(sync['student_ids'])
            retained = []
            for event in base:
                rule = by_id[event.uid.removeprefix('personal:')]
                participants = rule.get('student_ids') or [person_key(n) for n in people(event.title)]
                if not participants or not set(participants).issubset(covered) or rule['id'].startswith('lesson-'):
                    retained.append(event)
            base = retained
            for row in self.store.platform_events(day):
                base.append(Event(row['uid'], row['title'], datetime.fromisoformat(row['start']),
                                  datetime.fromisoformat(row['end']), 'personal', row['details'], row['cancelled']))
        result = []
        for event in base:
            key = event.uid+'|'+day.isoformat()
            patch = self.store.override(key)
            if patch:
                event = replace(event, title=patch['title'], start=datetime.fromisoformat(patch['start']),
                                end=datetime.fromisoformat(patch['end']), cancelled=patch.get('cancelled', False),
                                details=event.details+' · личная правка')
            if key in moved:
                original_rule = moved[key]['rule']
                target = by_id.get(original_rule['id'], original_rule)
                destination = date.fromisoformat(target.get('date', original_rule['date']))
                event = replace(event, cancelled=True,
                                details=event.details+f' · перенесено на {destination:%d.%m.%Y}')
            result.append(event)
        return sorted(result, key=lambda e: (e.start, e.title))

    async def upcoming(self, now, days=7):
        events, notes = {}, []
        for offset in range(days):
            entries, note, _ = await self.day(now.date() + timedelta(days=offset))
            for entry in entries:
                if not entry.cancelled and not entry.all_day and entry.end > now:
                    events[(entry.uid, entry.start)] = entry
            if note and note not in notes:
                notes.append(note)
        return sorted(events.values(), key=lambda e: e.start), notes
