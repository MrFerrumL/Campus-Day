"""Read-only import of Google and iCloud iCalendar feeds."""

from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from threading import BoundedSemaphore
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from icalendar import Calendar
import recurring_ical_events


GOOGLE = "calendar.google.com"
APPLE = re.compile(r"(?:p[0-9]+-)?caldav\.icloud\.com")
MAX_BYTES = 1024 * 1024
MAX_EVENTS = 2500
IMPORT_SLOTS = BoundedSemaphore(3)
INVALID_LINK = "Скопируйте ссылку iCal из Google Календаря или ссылку общего календаря iCloud."
INSTRUCTIONS = (
    "Google Календарь: Настройки → Интеграция календаря → адрес в формате iCal.\n"
    "Apple: Календари → ⓘ → Общедоступный календарь → Поделиться ссылкой.\n"
    "Вставьте ссылку в этот чат или в Mini App → Календарь → Импорт. "
    "Секретный адрес Google удобнее вставить в Mini App."
)


def is_calendar_link(value):
    return bool(re.match(r"^(?:webcal://|https://(?:calendar\.google\.com/calendar/ical/|"
                         r"(?:p[0-9]+-)?caldav\.icloud\.com/))", value, re.I))


def feed_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(INVALID_LINK)
    value = value.strip()
    try:
        url = urlsplit(value)
        valid_port = url.port in (None, 443)
    except ValueError:
        raise ValueError(INVALID_LINK) from None
    if (not valid_port or url.username is not None or url.query or url.fragment
            or any(ord(ch) < 33 for ch in value)):
        raise ValueError(INVALID_LINK)
    host, path = url.hostname or "", url.path
    if host == GOOGLE and url.scheme == "https":
        match = re.fullmatch(r"/calendar/ical/([^/]+)/(public|private-[A-Za-z0-9_-]+)/(basic|full)\.ics", path)
        if match:
            calendar_id = unquote(match[1])
            if calendar_id not in (".", "..") and re.fullmatch(r"[A-Za-z0-9_.@+\-]+", calendar_id):
                return f"https://{GOOGLE}/calendar/ical/{quote(calendar_id, safe='')}/{match[2]}/basic.ics"
    if APPLE.fullmatch(host) and url.scheme in ("https", "webcal"):
        if re.fullmatch(r"/published/2/[A-Za-z0-9_=-]+", path):
            return urlunsplit(("https", host, path, "", ""))
    raise ValueError(INVALID_LINK)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(url):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        request = Request(url, headers={"Accept": "text/calendar", "User-Agent": "CampusDay/1.0"})
        with opener.open(request, timeout=8) as response:
            body = response.read(MAX_BYTES + 1)
    except OSError:
        raise ValueError("Календарь недоступен. Проверьте адрес и настройки доступа.") from None
    if len(body) > MAX_BYTES:
        raise ValueError("Файл календаря слишком большой для импорта.")
    return body


def event_time(value, tz):
    if isinstance(value, datetime):
        return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    return datetime.combine(value, time.min, tz)


def clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def occurrences(body, now):
    tz = now.tzinfo
    first = datetime.combine(now.date() - timedelta(days=30), time.min, tz)
    last = datetime.combine(now.date() + timedelta(days=181), time.min, tz)
    try:
        calendar = Calendar.from_ical(body)
        raw_events = calendar.walk("VEVENT")
        if len(raw_events) > MAX_EVENTS:
            raise ValueError()
        series = {str(item.get("UID")) for item in raw_events
                  if any(field in item for field in ("RECURRENCE-ID", "RRULE", "RDATE"))}
        # Calendar feeds for schedules should contain at most one occurrence per
        # day per series. Bound expansion before handing the rule to the library.
        for item in raw_events:
            rule = item.get("RRULE")
            if rule and (str(rule["FREQ"][0]) not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
                         or any(len(rule.get(field, [])) > 1 for field in ("BYHOUR", "BYMINUTE", "BYSECOND"))):
                raise ValueError()
        events = recurring_ical_events.of(calendar).between(first, last)
        if len(events) > MAX_EVENTS:
            raise ValueError()
        result = {}
        for event in events:
            uid = str(event.get("UID") or "")
            if not uid or str(event.get("STATUS", "")).upper() == "CANCELLED":
                continue
            original = event.start
            start = event_time(original, tz)
            if not first <= start < last:
                continue
            all_day = not isinstance(original, datetime)
            if all_day:
                minutes = (event.end - original).days * 1440
            else:
                end = event_time(event.end, tz)
                minutes = (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 60
            recurrence = event.get("RECURRENCE-ID")
            instance = ""
            if uid in series and recurrence:
                instance = (event_time(recurrence.dt, tz).astimezone(timezone.utc).isoformat()
                            if isinstance(recurrence.dt, datetime) else recurrence.dt.isoformat())
            key = sha256(f"{uid}\n{instance}".encode()).hexdigest()
            name = clean(event.get("SUMMARY"), 140) or "Событие без названия"
            note = clean(event.get("LOCATION"), 500)
            result[key] = (name, start.isoformat(), max(1, int(minutes)), note, int(all_day))
        return result
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError, NotImplementedError):
        raise ValueError("Не удалось прочитать календарь. Проверьте формат и размер расписания.") from None


def fetch(value, now):
    url = feed_url(value)
    if not IMPORT_SLOTS.acquire(blocking=False):
        raise ValueError("Сейчас импортируется другой календарь. Повторите через минуту.")
    try:
        return sha256(url.encode()).hexdigest(), occurrences(download(url), now)
    finally:
        IMPORT_SLOTS.release()


def apply(store, source, events):
    counts = dict(added=0, updated=0, unchanged=0)
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        for key, fields in events.items():
            fingerprint = sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()
            row = store.db.execute(
                "SELECT item, fingerprint FROM imported_calendar WHERE source=? AND occurrence=?", (source, key),
            ).fetchone()
            if row is None:
                item = store.db.execute(
                    "INSERT INTO items(kind,title,due,duration,note,all_day) VALUES ('event',?,?,?,?,?)", fields,
                ).lastrowid
                store.db.execute("INSERT INTO imported_calendar VALUES (?,?,?,?)", (source, key, item, fingerprint))
                counts["added"] += 1
            elif row["fingerprint"] != fingerprint:
                changed = store.db.execute(
                    "UPDATE items SET title=?,due=?,duration=?,note=?,all_day=? WHERE id=?", fields + (row["item"],),
                ).rowcount
                store.db.execute("UPDATE imported_calendar SET fingerprint=? WHERE source=? AND occurrence=?",
                                 (fingerprint, source, key))
                counts["updated" if changed else "unchanged"] += 1
            else:
                counts["unchanged"] += 1
    return counts


def summary(counts):
    if not any(counts.values()):
        return "В выбранном периоде нет событий для импорта."
    return f"Добавлено {counts['added']} · обновлено {counts['updated']} · без изменений {counts['unchanged']}"
