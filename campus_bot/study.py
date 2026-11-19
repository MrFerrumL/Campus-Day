"""University overview for the Mini App: attendance per subject this semester and
the coming colloquia. Built from the cached timetable weeks and the marks."""
import json
from datetime import date, datetime

from .schedule import parse_university


def semester_start(today):
    """Autumn from 1 September, spring from 1 February."""
    return date(today.year, 9, 1) if today.month >= 8 else date(today.year if today.month >= 2 else today.year - 1,
                                                                   2 if today.month >= 2 else 9, 1)


def attendance_by_subject(store, config, today):
    first, group = semester_start(today), store.get('group_id')
    titles = {}
    for value, in store.db.execute("SELECT value FROM cache WHERE key LIKE ?", (f'uni:{group}:%',)):
        try:
            events = parse_university(json.loads(value), config.timezone, group)
        except (ValueError, KeyError, TypeError):
            continue
        for event in events:
            day = event.start.date()
            if first <= day <= today and not event.cancelled and not event.all_day:
                titles[f'{event.uid}|{day.isoformat()}'] = event.title
    marks = dict(store.db.execute('SELECT key, status FROM attendance').fetchall())
    rows = {}
    for key, title in titles.items():
        row = rows.setdefault(title, dict(subject=title, present=0, absent=0, unmarked=0))
        status = marks.get(key) or ('present' if store.checked(key) else 'pending')
        row['present' if status == 'present' else 'absent' if status == 'absent' else 'unmarked'] += 1
    return dict(since=first.isoformat(), subjects=sorted(rows.values(), key=lambda r: (-r['absent'], r['subject'])))


def upcoming(store, config, now, limit=8):
    """Colloquia and other announced university events from now on."""
    group, rows = store.get('group_id'), []
    for row in store.get('university_extras', []):
        if row.get('group_id') != group:
            continue
        start = datetime.fromisoformat(row['start'])
        start = start.replace(tzinfo=config.timezone) if start.tzinfo is None else start
        if start >= now:
            rows.append(dict(title=row['title'], start=start.isoformat(), details=row.get('details', '')))
    return sorted(rows, key=lambda r: r['start'])[:limit]


def overview(store, config, schedule, now):
    group_id=store.get('group_id')
    return dict(**attendance_by_subject(store, config, now.date()), upcoming=upcoming(store, config, now),
                subgroup=group_id if group_id else None, group=store.get('group_name'),
                group_id=group_id, public_mode=config.public_mode,
                anchor=store.get('cycle_anchor', schedule.anchor.isoformat()))
