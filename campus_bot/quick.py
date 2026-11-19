"""One-line task entry: «завтра 18:00 сдать лабу», «в пятницу отчёт», «каждый день 7:30 зарядка».

Recognises a date (сегодня, завтра, послезавтра, a weekday, ДД.ММ[.ГГГГ]), a time
(18:00, 9.30, «в 18»), a repeat (каждый день / по будням / каждую неделю) and
importance («!» or «важно»); everything else is the title.
"""
import re
from datetime import date, datetime, timedelta

from .daily_plan import priority_text

WEEKDAY_FORMS = {
    0: ('понедельник', 'пн'), 1: ('вторник', 'вт'), 2: ('среда', 'среду', 'ср'), 3: ('четверг', 'чт'),
    4: ('пятница', 'пятницу', 'пт'), 5: ('суббота', 'субботу', 'сб'), 6: ('воскресенье', 'вс'),
}
WEEKDAY = {form: number for number, forms in WEEKDAY_FORMS.items() for form in forms}
REPEATS = (
    (re.compile(r'\b(?:каждый\s+день|ежедневно)\b', re.I), 'daily'),
    (re.compile(r'\b(?:по\s+будням|каждый\s+будний\s+день)\b', re.I), 'weekdays'),
    (re.compile(r'\b(?:каждую\s+неделю|еженедельно)\b', re.I), 'weekly'),
    (re.compile(r'\bкажд(?:ый|ую|ое)\s+(?=(?:' + '|'.join(sorted(WEEKDAY, key=len, reverse=True)) + r')\b)', re.I), 'weekly'),
)
RELATIVE = {'сегодня': 0, 'завтра': 1, 'послезавтра': 2}
# Only real day and month numbers, so «8.15» stays a time.
# Short units must end the word («м» is metres, not «матан»); longer stems take any ending («часа», «раза»).
UNITS = r'(?:(?:кг|г|гр|л|мл|м|км|см|мм|шт)\b|(?:раз|час|минут|дн|недел|месяц|год|лет|задач|пар|урок|человек)\w*|%)'
DATE = re.compile(r'(?<![\d.])\b(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])(?:\.(\d{4}))?\b(?!\s*' + UNITS + ')', re.I)
# «в 18» is a time, «в 2 часа» or «в 3 раза» is a quantity.
TIME = re.compile(r'(?:\bв\s+)?\b([01]?\d|2[0-3])[:.]([0-5]\d)\b(?!\s*' + UNITS + ')'
                  r'|\bв\s+([01]?\d|2[0-3])\b(?!\s*[.:]?\d)(?!\s*' + UNITS + ')', re.I)
# A weekday counts only with «в/во/на» («в среду») or as a short form at the start («пт отчёт»),
# so «среда разработки» stays a title.
_FULL = '|'.join(sorted((f for f in WEEKDAY if len(f) > 2), key=len, reverse=True))
_SHORT = '|'.join(f for f in WEEKDAY if len(f) == 2)
WORD_DAY = re.compile(r'\b(сегодня|завтра|послезавтра)\b|\b(?:во?|на)\s+(' + _FULL + r')\b|^(' + _SHORT + r')\b', re.I)


def _cut(text, match):
    return (text[:match.start()] + ' ' + text[match.end():]).strip()


def parse_quick(text, now):
    """dict(title, due, all_day, priority, recurrence) for a datetime-aware `now`."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Напишите задачу, например: завтра 18:00 сдать лабу')
    rest, priority = priority_text(text.strip())
    if rest.endswith('!'):
        rest, priority = rest.rstrip('!').strip(), 1
    recurrence = 'once'
    for pattern, kind in REPEATS:
        found = pattern.search(rest)
        if found:
            # «каждый понедельник» keeps its weekday as a date: «в понедельник».
            recurrence, rest = kind, rest[:found.start()] + (' в ' if found[0].lower().startswith('кажд') and kind == 'weekly'
                                                            and not re.match(r'каждую\s+неделю', found[0], re.I) else ' ') + rest[found.end():]
            rest = rest.strip()
            break
    day, explicit_day = now.date(), False
    found = DATE.search(rest)
    if found:
        year = int(found[3]) if found[3] else now.year
        try:
            day = date(year, int(found[2]), int(found[1]))
        except ValueError:
            raise ValueError(f'Такой даты нет: {found[0]}') from None
        explicit_day, rest = True, _cut(rest, found)
        if not found[3] and day < now.date() - timedelta(days=31):
            day = day.replace(year=year + 1)
    else:
        found = WORD_DAY.search(rest)
        if found:
            word = (found[1] or found[2] or found[3]).lower()
            shift = RELATIVE[word] if word in RELATIVE else (WEEKDAY[word] - now.weekday()) % 7
            day, explicit_day, rest = now.date() + timedelta(days=shift), True, _cut(rest, found)
    found = TIME.search(rest)
    all_day = not found
    if found:
        hour, minute = (int(found[1]), int(found[2])) if found[1] else (int(found[3]), 0)
        rest = _cut(rest, found)
    else:
        hour, minute = 23, 59
    due = datetime.combine(day, datetime.min.time(), now.tzinfo).replace(hour=hour, minute=minute)
    if not explicit_day and not all_day and due <= now:
        due += timedelta(days=1)  # «18:00 позвонить» after six means tomorrow
    title = re.sub(r'\s{2,}', ' ', rest).strip(' ,.—–-')
    if not 1 <= len(title) <= 300:
        raise ValueError('Не понял, что сделать. Пример: завтра 18:00 сдать лабу')
    return dict(title=title[0].upper() + title[1:], due=due.isoformat(), all_day=all_day, priority=priority,
                recurrence=recurrence)
