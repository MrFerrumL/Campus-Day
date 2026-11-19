"""Training progress from finished workouts: records, per-exercise history, weekly totals.

Pure functions over workout rows, so they are easy to test and cheap to run on
the few hundred workouts a person logs in a year or two.
"""
from datetime import date, timedelta

WEEKS = 12
RECORD_WINDOW = 30  # newest workouts whose new records are reported back to the app
# Within one exercise a weighted estimate outranks plain reps (time is its own unit).
RANK = {'reps': 0, 'weight': 1, 'time': 0}


def epley(weight, reps):
    """Estimated one-rep max; only meaningful for a weighted set of 1–30 reps."""
    return round(weight * (1 + reps / 30), 1) if weight and reps and 0 < reps <= 30 else None


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def best_of(entry):
    """(metric kind, best value, the set that gave it) for one exercise in one workout."""
    sets = [s for s in entry.get('sets', []) if s.get('done')]
    unit = entry.get('unit', 'reps')
    if not sets:
        return None
    if unit in ('seconds', 'minutes'):
        top = max(sets, key=lambda s: _number(s.get('reps')) or 0)
        return 'time', _number(top.get('reps')) or 0, top
    weighted = [(epley(_number(s.get('weight')), _number(s.get('reps'))), s) for s in sets]
    weighted = [(v, s) for v, s in weighted if v]
    if weighted:
        value, top = max(weighted, key=lambda item: item[0])
        return 'weight', value, top
    top = max(sets, key=lambda s: _number(s.get('reps')) or 0)
    return 'reps', _number(top.get('reps')) or 0, top


def _volume(entry):
    if entry.get('unit', 'reps') != 'reps':
        return 0
    return sum((_number(s.get('weight')) or 0) * (_number(s.get('reps')) or 0) for s in entry.get('sets', []) if s.get('done'))


def _monday(day):
    return day - timedelta(days=day.weekday())


def progress(workouts, today):
    """Everything the progress screen needs, from finished workouts in any order."""
    done = sorted((w for w in workouts if w.get('status') == 'done'), key=lambda w: w.get('ended') or w['day'])
    history, records, prs = {}, {}, {}
    for w in done:
        for entry in w.get('exercises', []):
            best = best_of(entry)
            if not best:
                continue
            kind, value, top = best
            uid = entry['exercise_id']
            series = history.get(uid)
            if series and series['kind'] != kind:
                # Reps without weight and an estimated max in kg cannot share one line or one record.
                if RANK.get(kind, 0) < RANK.get(series['kind'], 0):
                    continue  # a bodyweight session after weighted ones: keep the weighted series
                series = None  # the first weighted session starts a new series
                records.pop(uid, None)
            if series is None:
                series = history[uid] = dict(kind=kind, unit=entry.get('unit', 'reps'), name=entry.get('name', ''), points=[])
            sets = sum(1 for s in entry['sets'] if s.get('done'))
            point = dict(day=w['day'], value=value, weight=top.get('weight'), reps=top.get('reps'),
                         volume=round(_volume(entry), 1), sets=sets)
            last = series['points'][-1] if series['points'] else None
            if last and last['day'] == w['day']:
                # Two workouts on one day make one point: the best set, all sets and volume together.
                merged = point if value > last['value'] else dict(last)
                merged.update(sets=last['sets'] + sets, volume=round(last['volume'] + point['volume'], 1))
                series['points'][-1] = merged
            else:
                series['points'].append(point)
            old = records.get(uid)
            if old is None or value > old['value']:
                if old is not None:  # the very first time is a start, not a record
                    prs.setdefault(w['id'], []).append(uid)
                records[uid] = dict(kind=kind, value=value, weight=top.get('weight'), reps=top.get('reps'), day=w['day'])
    start = _monday(today) - timedelta(weeks=WEEKS - 1)
    weeks = [dict(start=(start + timedelta(weeks=i)).isoformat(), workouts=0, sets=0, volume=0.0) for i in range(WEEKS)]
    days = {}
    for w in done:
        day = date.fromisoformat(w['day'])
        if day < start or day > today:
            continue
        week = weeks[(_monday(day) - start).days // 7]
        week['workouts'] += 1
        week['sets'] += sum(1 for e in w['exercises'] for s in e['sets'] if s.get('done'))
        week['volume'] = round(week['volume'] + sum(_volume(e) for e in w['exercises']), 1)
        days[w['day']] = days.get(w['day'], 0) + 1
    streak = 0
    for week in reversed(weeks):
        if week['workouts']:
            streak += 1
        elif week is not weeks[-1]:  # the current week may still be empty
            break
    recent_ids = {w['id'] for w in done[-RECORD_WINDOW:]}
    return dict(history=history, records=records, weeks=weeks, days=days, streak=streak,
                prs={k: v for k, v in prs.items() if k in recent_ids}, total=len(done))
