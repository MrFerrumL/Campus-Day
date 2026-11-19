"""Food, water and sleep summaries: the last 7 days, meals eaten often, and the card of the day."""
from datetime import timedelta

FREQUENT = 6


def _sum(rows, field):
    return round(sum(r.get(field) or 0 for r in rows), 1)


def week(records, day):
    """Totals for the 7 days ending on `day` (the date shown in the journal)."""
    out = []
    for i in range(6, -1, -1):
        d = (day - timedelta(days=i)).isoformat()
        meals = [r for r in records['meal'] if r['day'] == d]
        sleep = [r for r in records['sleep'] if r['day'] == d]
        out.append(dict(day=d, calories=_sum(meals, 'calories'), protein=_sum(meals, 'protein'),
                        meals=len(meals), water_ml=_sum([r for r in records['water'] if r['day'] == d], 'ml'),
                        sleep_minutes=sum(r['minutes'] for r in sleep),
                        quality=round(sum(r['quality'] for r in sleep) / len(sleep), 1) if sleep else None))
    return out


def frequent(meals):
    """Meals logged at least twice, most often first; each keeps its latest numbers for a one-tap repeat."""
    seen = {}
    for meal in sorted(meals, key=lambda r: (r['day'], r.get('time') or '')):
        key = ' '.join(meal['name'].lower().split())
        item = seen.setdefault(key, dict(count=0))
        item.update(count=item['count'] + 1, last=meal['day'], name=meal['name'], time=meal.get('time'),
                    **{k: meal.get(k) for k in ('calories', 'protein', 'fat', 'carbs')})
    ranked = sorted((v for v in seen.values() if v['count'] >= 2), key=lambda v: (v['count'], v['last']), reverse=True)
    return [dict(name=v['name'], count=v['count'], time=v['time'], calories=v['calories'], protein=v['protein'], fat=v['fat'], carbs=v['carbs'])
            for v in ranked[:FREQUENT]]


def card(rows_for_day, settings, active, day):
    """The small wellness card on the Today screen: only today's rows, nothing heavy."""
    meals, water, sleep, workouts = (rows_for_day.get(k, []) for k in ('meal', 'water', 'sleep', 'workout'))
    done = [w for w in workouts if w['status'] == 'done']
    progress = None
    if active:
        sets = [s for e in active['exercises'] for s in e['sets']]
        progress = dict(name=active['name'], done=sum(1 for s in sets if s['done']), total=len(sets))
    return dict(day=day.isoformat(), calories=_sum(meals, 'calories'), protein=_sum(meals, 'protein'), meals=len(meals),
                water_ml=_sum(water, 'ml'), sleep_minutes=sum(r['minutes'] for r in sleep),
                workouts=[w['name'] for w in done], active=progress,
                goals={k: settings.get(k) for k in ('calories', 'protein', 'water_ml', 'sleep_hours')})
