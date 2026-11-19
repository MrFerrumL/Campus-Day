"""Steps, runs, rides, gym sessions and other activity with the calories they burn.

Burn is the active part only, above what the body spends at rest anyway:
(MET − 1) × weight × hours, with MET from the Compendium of Physical Activities
(Ainsworth et al., 2011). Walking, running and cycling take the MET from the speed when
both distance and time are known. Steps cost about 0.5 kcal per kg per km, with the
stride estimated from height. A daily calorie target already covers rest, so only this
active part is set against what was eaten.
"""
from datetime import date, datetime
import math
import re
from uuid import uuid4

# id: (name, stems, fixed MET or None for speed-based, default km/h when only distance is given)
TYPES = {
    'walk': ('Ходьба', 'ходьб|прогулк|гулял|погулял|пешк|пешеход', None, 5.0),
    'run': ('Бег', 'бег|пробеж|бегал|пробежал|джогг', None, 10.0),
    'bike': ('Велосипед', 'велосипед|велик|велопрогул|покатался на велосипед', None, 18.0),
    'spin': ('Велотренажёр', 'велотренаж|сайкл', 7.0, 0),
    'swim': ('Плавание', 'плаван|плавал|проплыл|бассейн', 7.0, 2.5),
    'row': ('Гребля', 'гребл|байдар|каноэ', 7.0, 10.0),
    'erg': ('Гребной тренажёр', 'гребн тренаж|эргометр|концепт', 7.0, 0),
    'elliptical': ('Эллипс', 'эллипс|орбитрек', 5.0, 0),
    'stairs': ('Лестница, степпер', 'лестниц|степпер|ступен', 8.0, 0),
    'rope': ('Скакалка', 'скакалк', 11.8, 0),
    'hiit': ('Интервальная тренировка', 'интервальн|hiit|хиит|кроссфит|табата', 8.0, 0),
    'gym': ('Силовая в зале', 'зал|силов|тренажер|штанг|качал|железо', 5.0, 0),
    'football': ('Футбол', 'футбол', 7.0, 0),
    'basketball': ('Баскетбол', 'баскетбол', 6.5, 0),
    'volleyball': ('Волейбол', 'волейбол', 4.0, 0),
    'tennis': ('Теннис', 'теннис', 7.3, 0),
    'pingpong': ('Настольный теннис', 'настольн|пинг', 4.0, 0),
    'boxing': ('Бокс, единоборства', 'бокс|единоборств|борьб|карате|самбо', 7.8, 0),
    'yoga': ('Йога', 'йог', 2.5, 0),
    'stretch': ('Растяжка', 'растяжк|стретч|заминк', 2.3, 0),
    'dance': ('Танцы', 'танц', 5.0, 0),
    'hike': ('Поход', 'поход|хайкинг|треккинг', 6.0, 4.0),
    'ski': ('Лыжи', 'лыж', 7.0, 8.0),
    'skate': ('Коньки, ролики', 'коньк|ролик', 7.0, 12.0),
}
# (km/h up to, MET): Compendium values for walking, running and cycling by speed.
SPEED_MET = {
    'walk': [(3.2, 2.8), (4.0, 3.0), (4.8, 3.5), (5.6, 4.3), (6.4, 5.0), (7.2, 7.0), (99, 8.3)],
    'run': [(7.0, 6.0), (8.0, 8.3), (9.7, 9.0), (10.8, 9.8), (11.3, 10.5), (12.1, 11.0), (12.9, 11.5),
            (13.8, 11.8), (14.5, 12.3), (16.1, 12.8), (99, 14.5)],
    'bike': [(16.0, 4.0), (19.2, 6.8), (22.4, 8.0), (25.6, 10.0), (30.6, 12.0), (99, 15.8)],
}
GYM_MET = 5.0          # a workout logged in workout mode
# A pedometer already counts these, so with steps for the day they add nothing more.
IN_STEPS = {'walk', 'hike'}
STEP_KCAL_PER_KG_KM = 0.5
STRIDE_PER_HEIGHT = 0.415
DEFAULT_STRIDE_M = 0.74
MAX_MINUTES = 600
MAX_KM = 300
MAX_STEPS = 100_000
MAX_WORKOUT_HOURS = 4

WORD = re.compile(r'[a-zа-я0-9.]+')
MINUTES = re.compile(r'(?<!в )(?<!\d)(\d+(?:\.\d+)?)\s*(?:мин\w*|m\b)')
HOURS = re.compile(r'(?<!в )(?<!к )(?<!\d)(\d+(?:\.\d+)?)\s*(?:ч(?![а-я/])|час\w*|h\b)')
KM = re.compile(r'(\d+(?:\.\d+)?)\s*(?:км|килом\w*|km)(?![/\w])')
SPEED = re.compile(r'(\d+(?:\.\d+)?)\s*км\s*/\s*ч')
METRES = re.compile(r'(\d+)\s*(?:м|метр\w*)(?![\w])')
STEPS = re.compile(r'(\d+(?:\.\d+)?)\s*(тыс\w*\.?|к|k)?\s*шаг\w*')


def normalize(text):
    text = str(text).lower().replace('ё', 'е')
    text = re.sub(r'(\d)\s(?=\d{3}\b)', r'\1', text)  # «10 000» → «10000»
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    return text.replace('полчаса', '30 мин').replace('полтора часа', '90 мин')


def find_type(text):
    """The most specific activity named in the text: longest matching stem wins."""
    words = WORD.findall(text)
    best = None
    for uid, (_, stems, _, _) in TYPES.items():
        for way in stems.split('|'):
            parts = way.split()
            if all(any(w.startswith(p) for w in words) for p in parts):
                score = (len(parts), sum(map(len, parts)))
                if not best or score > best[0]:
                    best = (score, uid)
    return best[1] if best else None


def parse(text):
    """{'steps': n} or {'type', 'minutes', 'distance_km'} from «пробежал 5 км за 30 минут», or None."""
    t = normalize(text)
    steps = STEPS.search(t)
    if steps:
        n = float(steps.group(1)) * (1000 if steps.group(2) else 1)
        return dict(steps=int(n)) if 0 < n <= MAX_STEPS else None
    kind = find_type(t)
    if not kind:
        return None
    minutes = sum(float(m) for m in MINUTES.findall(t)) + 60 * sum(float(h) for h in HOURS.findall(t))
    if not minutes and re.search(r'(?<![а-я])час(?![а-я])', t):
        minutes = 60
    km = KM.search(t)
    distance = float(km.group(1)) if km else None
    speed = SPEED.search(t)
    if distance is None and speed and minutes:
        distance = round(float(speed.group(1)) * minutes / 60, 2)
    if distance is None and kind == 'swim' and METRES.search(t):
        distance = int(METRES.search(t).group(1)) / 1000
    if not minutes and distance and TYPES[kind][3]:
        minutes = distance / TYPES[kind][3] * 60
    if not minutes:
        return None
    return dict(type=kind, minutes=round(minutes), distance_km=distance)


def met_for(kind, minutes, distance_km):
    name, _, fixed, default_speed = TYPES[kind]
    if fixed is not None:
        return fixed
    speed = distance_km / (minutes / 60) if distance_km and minutes else default_speed
    return next(met for upto, met in SPEED_MET[kind] if speed <= upto)


def active_kcal(met, weight, minutes):
    return round(max(met - 1, 0) * weight * minutes / 60) if weight else None


def stride_m(height_cm):
    return STRIDE_PER_HEIGHT * height_cm / 100 if height_cm else DEFAULT_STRIDE_M


def steps_km(steps, height_cm):
    return round(steps * stride_m(height_cm) / 1000, 2)


def steps_kcal(steps, weight, height_cm):
    return round(STEP_KCAL_PER_KG_KM * weight * steps_km(steps, height_cm)) if weight else None


def number(value, low, high, optional=False):
    if optional and value in (None, ''):
        return None
    if isinstance(value, bool):
        raise ValueError('Введите число')
    try:
        n = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError('Введите число') from None
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError('Число вне допустимого диапазона')
    return n


def journal_day(body, now):
    day = date.fromisoformat(str(body.get('day') or now.date().isoformat()))
    if day > now.date():
        raise ValueError('Журнал — для сегодняшних и прошедших дней')
    return day.isoformat()


def build(journal, action, body, now):
    """Validated row for wellness-steps / wellness-activity; the caller stores it."""
    settings = journal.store.get('wellness_settings', {}) or {}
    weight, height = settings.get('weight_kg'), settings.get('height_cm')
    day = journal_day(body, now)
    if action == 'wellness-steps':
        steps = int(number(body.get('steps'), 0, MAX_STEPS))
        return 'steps', dict(id='steps-' + day, day=day, steps=steps, km=steps_km(steps, height),
                             kcal=steps_kcal(steps, weight, height))
    kind = body.get('type')
    if kind not in TYPES:
        raise ValueError('Выберите вид активности из списка')
    minutes = number(body.get('minutes'), 1, MAX_MINUTES)
    distance = number(body.get('distance_km'), 0, MAX_KM, True)
    uid = body.get('id') or 'activity-' + uuid4().hex[:12]
    if body.get('id'):
        old = journal.get(uid, 'activity')
        if not body.get('day'):
            day = old['day']
    try:
        clock = datetime.strptime(str(body.get('time') or now.strftime('%H:%M')), '%H:%M').strftime('%H:%M')
    except ValueError:
        raise ValueError('Время: ЧЧ:ММ') from None
    note = str(body.get('note') or '').strip()
    if len(note) > 300:
        raise ValueError('Заметка: до 300 символов')
    met = met_for(kind, minutes, distance)
    return 'activity', dict(id=uid, day=day, time=clock, type=kind, name=TYPES[kind][0], minutes=round(minutes),
                            distance_km=distance, met=met, kcal=active_kcal(met, weight, minutes), note=note)


def workout_minutes(workout):
    if workout.get('status') != 'done' or not workout.get('started') or not workout.get('ended'):
        return 0
    try:
        span = datetime.fromisoformat(workout['ended']) - datetime.fromisoformat(workout['started'])
    except (TypeError, ValueError):
        return 0
    return max(0, min(span.total_seconds() / 60, MAX_WORKOUT_HOURS * 60))


def day_summary(rows, settings, day):
    """Steps, activities and gym workouts of one day with the active calories they burned."""
    weight, height = settings.get('weight_kg'), settings.get('height_cm')
    day = str(day)
    steps_row = next((r for r in rows.get('steps', []) if r['day'] == day), None)
    steps = steps_row['steps'] if steps_row else 0
    items = []
    for r in sorted((r for r in rows.get('activity', []) if r['day'] == day), key=lambda r: r.get('time') or ''):
        kcal = r.get('kcal') if r.get('kcal') is not None else active_kcal(r['met'], weight, r['minutes'])
        items.append(dict(r, kcal=kcal))
    for w in rows.get('workout', []):
        minutes = workout_minutes(w) if w['day'] == day else 0
        if minutes >= 1:
            items.append(dict(id=w['id'], day=day, time=w['started'][11:16], type='gym', name=w.get('name') or 'Тренировка в зале',
                              minutes=round(minutes), distance_km=None, met=GYM_MET, kcal=active_kcal(GYM_MET, weight, minutes),
                              workout=True))
    logged_gym = any(i.get('workout') for i in items)
    for i in items:
        if steps and i['type'] in IN_STEPS:
            i['counted'], i['why'] = False, 'уже в шагах'
        elif logged_gym and i['type'] == 'gym' and not i.get('workout'):
            i['counted'], i['why'] = False, 'уже в журнале тренировок'
        else:
            i['counted'] = True
    step_kcal = steps_kcal(steps, weight, height) if steps else 0
    burned = (step_kcal or 0) + sum(i['kcal'] or 0 for i in items if i['counted']) if weight else None
    return dict(steps=steps, steps_km=steps_km(steps, height), steps_kcal=step_kcal, items=items, burned=burned,
                minutes=sum(i['minutes'] for i in items), weight_known=bool(weight))


def describe(entry):
    """«Бег 30 мин, 5 км — 380 ккал» for chat replies."""
    parts = [f'{entry["name"]} {entry["minutes"]} мин']
    if entry.get('distance_km'):
        parts.append(f'{entry["distance_km"]:g} км')
    kcal = f' — {entry["kcal"]} ккал' if entry.get('kcal') is not None else ''
    return ', '.join(parts) + kcal
