from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
DAY_CODES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass(frozen=True)
class Event:
    uid: str
    title: str
    start: datetime
    end: datetime
    source: str
    details: str = ""
    cancelled: bool = False
    all_day: bool = False

    @property
    def time_label(self):
        if self.all_day:
            return "весь день"
        if self.start == self.end:
            return f"с {self.start:%H:%M}"
        return f"{self.start:%H:%M}–{self.end:%H:%M}"


def at(day: date, clock: str, tz) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), tzinfo=tz)


def clock(value: str) -> str:
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.strftime("%H:%M")


def parse_day(value: str, today: date) -> date:
    value = value.strip().lower()
    aliases = {"сегодня": today, "today": today, "завтра": today + timedelta(days=1),
               "tomorrow": today + timedelta(days=1), "послезавтра": today + timedelta(days=2)}
    if value in aliases:
        return aliases[value]
    short = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
    if value in WEEKDAYS or value in short or value in DAY_CODES:
        weekday = WEEKDAYS.index(value) if value in WEEKDAYS else short.index(value) if value in short else DAY_CODES[value]
        return today + timedelta(days=(weekday-today.weekday()) % 7)
    if "." in value:
        parts = value.rstrip('.').split('.')
        if len(parts) not in (2,3):
            raise ValueError("Дата: ДД.ММ или ДД.ММ.ГГГГ")
        return date(int(parts[2]) if len(parts) == 3 else today.year, int(parts[1]), int(parts[0]))
    return date.fromisoformat(value)


def overlaps(events: list[Event]):
    active = sorted((e for e in events if not e.cancelled and not e.all_day), key=lambda e: e.start)
    return [(a, b) for i, a in enumerate(active) for b in active[i + 1:] if b.start < a.end]


def free_slots(events: list[Event], day: date, tz, minutes=30, after=None):
    lower, upper = at(day, "08:00", tz), at(day, "23:00", tz)
    cursor = max(lower, after) if after else lower
    result = []
    for event in sorted(events, key=lambda e: e.start):
        # An announced start without an end cannot establish any later free time.
        end = upper if event.start == event.end else event.end
        if event.cancelled or event.all_day or end <= cursor or event.start >= upper:
            continue
        if event.start - cursor >= timedelta(minutes=minutes):
            result.append((cursor, min(event.start, upper)))
        cursor = max(cursor, end)
    if upper - cursor >= timedelta(minutes=minutes):
        result.append((cursor, upper))
    return result
