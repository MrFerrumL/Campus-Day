"""The tutor's own income for a month: each lesson's price times the tutor's share.

Built from the billing rows (reollity.bill), so the dates and prices are exactly
those shown to pupils. Amounts are in kopecks.
"""
from datetime import date, timedelta

DEFAULT_SHARE = 50


def share_of(store, student):
    """The tutor's percent for a pupil: the pupil's own value, else the general one."""
    value = student.get('share')
    return int(value if value is not None else store.get('tutoring_share', DEFAULT_SHARE))


def valid_share(value):
    """A whole percent from 0 to 100, given as a number or digits."""
    text = str(value).strip()
    if isinstance(value, bool) or not text.isdigit() or not 0 <= int(text) <= 100:
        raise ValueError('Доля — целое число от 0 до 100')
    return int(text)


def income(rows, month):
    """forecast: all lessons of the month; conducted: those marked as held;
    received: the tutor's part of payments that came in this month (Reollity)."""
    first = date.fromisoformat(month + '-01')
    weeks, unknown = {}, 0
    forecast = conducted = received = 0
    pupils = []
    for row in rows:
        share = row.get('share', DEFAULT_SHARE)
        mine = own = 0
        for lesson in row['dates']:
            if lesson['amount'] is None:
                unknown += 1
                continue
            part = lesson['amount'] * share // 100
            mine += part
            if lesson['done']:
                own += part
            day = date.fromisoformat(lesson['day'])
            monday = (day - timedelta(days=day.weekday())).isoformat()
            weeks[monday] = weeks.get(monday, 0) + part
        paid = (row.get('current') or {}).get('paid') or 0
        forecast, conducted, received = forecast + mine, conducted + own, received + paid * share // 100
        if row['dates']:
            pupils.append(dict(id=row['id'], name=row['name'], lessons=len(row['dates']), share=share, income=mine))
    pupils.sort(key=lambda p: (-p['income'], p['name'].casefold()))
    ordered = sorted(weeks.items())
    return dict(month=first.strftime('%Y-%m'), forecast=forecast, conducted=conducted, received=received,
                unknown=unknown, weeks=[dict(start=start, amount=amount) for start, amount in ordered], pupils=pupils)
