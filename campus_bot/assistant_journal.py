"""Food, water and sleep entries the assistant may add: checked, written and described.

The model proposes; this module checks every field before anything is written, writes
through the same journal rules as the app (no future days, no overlapping sleep),
and describes each entry for the preview and the undo message.
"""
from datetime import datetime, timedelta
import json

from .wellness import Wellness

OPS = ('log_meal', 'log_water', 'log_sleep')
LIMITS = dict(calories=10000, protein=1000, fat=1000, carbs=2000)
MAX_DAYS_BACK = 30


def _moment(value, now, field):
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'Неверное время ({field})') from None
    moment = moment.replace(tzinfo=now.tzinfo) if moment.tzinfo is None else moment.astimezone(now.tzinfo)
    if moment > now:
        raise ValueError('Дневник — только для того, что уже было')
    if moment < now - timedelta(days=MAX_DAYS_BACK):
        raise ValueError(f'Записать можно за последние {MAX_DAYS_BACK} дней')
    return moment


def validate(op, now):
    """A clean copy of a journal operation, or ValueError with a short reason."""
    action = op['action']
    if op['id'] is not None:
        raise ValueError('Запись дневника всегда новая')
    if action == 'log_meal':
        title = op['title']
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 150:
            raise ValueError('Как называется блюдо?')
        for field, high in LIMITS.items():
            value = op[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= high):
                raise ValueError('Проверьте калории и БЖУ')
        when = _moment(op['due'], now, 'еда') or now
        return dict(op, title=title.strip(), due=when.isoformat())
    if action == 'log_water':
        ml = op['ml']
        if type(ml) is not int or not 1 <= ml <= 5000:
            raise ValueError('Сколько воды записать, в мл?')
        when = _moment(op['due'], now, 'вода') or now
        return dict(op, due=when.isoformat())
    start = _moment(op['due'], now, 'начало сна')
    end = _moment(op['end'], now, 'пробуждение')
    if start is None or end is None or not 1 <= (end - start).total_seconds() / 60 <= 1440:
        raise ValueError('Когда вы заснули и проснулись?')
    if op['quality'] is not None and op['quality'] not in (1, 2, 3, 4, 5):
        raise ValueError('Самочувствие — от 1 до 5')
    return dict(op, due=start.isoformat(), end=end.isoformat())


def write(store, op, now):
    """Write one checked entry inside the caller's transaction; returns the stored row."""
    journal = Wellness(store, now.tzinfo)
    when = datetime.fromisoformat(op['due'])
    if op['action'] == 'log_meal':
        body = dict(name=op['title'], day=when.date().isoformat(), time=when.strftime('%H:%M'),
                    **{k: op[k] for k in LIMITS})
        return journal._mutate('wellness-meal', body, now)
    if op['action'] == 'log_water':
        return journal._mutate('wellness-water', dict(ml=op['ml'], day=when.date().isoformat()), now)
    end = datetime.fromisoformat(op['end'])
    body = dict(day=end.date().isoformat(), start=op['due'], end=op['end'], quality=op['quality'] or 3)
    return journal._mutate('wellness-sleep', body, now)


def describe(op):
    """One line for the preview and the saved summary."""
    when = datetime.fromisoformat(op['due'])
    if op['action'] == 'log_meal':
        kcal = f' · {round(op["calories"])} ккал' if op['calories'] is not None else ''
        return f'🍽 {op["title"]}{kcal} · {when:%d.%m %H:%M}'
    if op['action'] == 'log_water':
        return f'💧 Вода {op["ml"]} мл · {when:%d.%m}'
    end = datetime.fromisoformat(op['end'])
    minutes = round((end - when).total_seconds() / 60)
    return f'🌙 Сон {when:%H:%M}–{end:%H:%M} ({minutes // 60} ч {minutes % 60} мин)'


def context(store, now):
    """What the model may see of the journal: today's numbers and goals, nothing older."""
    journal = Wellness(store, now.tzinfo)
    card = journal.today_card(now)
    rows = store.db.execute("SELECT value FROM wellness WHERE kind='meal' AND day=?", (now.date().isoformat(),))
    meals = [dict(name=r['name'], time=r.get('time'), calories=r.get('calories')) for r in map(lambda row: json.loads(row[0]), rows)][:20]
    return dict(today=dict(calories=card['calories'], protein=card['protein'], water_ml=card['water_ml'],
                           sleep_minutes=card['sleep_minutes'], workouts=card['workouts'], meals=meals),
                goals=card['goals'])
