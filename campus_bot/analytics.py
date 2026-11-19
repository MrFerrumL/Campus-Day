from datetime import date, datetime, timedelta


def task_analytics(rows,first,last,now):
    leaves=[r for r in rows if not r.get('is_group')]
    planned=[r for r in leaves if first.isoformat()<=r['due'][:10]<=last.isoformat()]
    def completed_day(row):
        if not row['done'] or not row.get('done_at'):
            return None
        if len(row['done_at'])==10:
            return date.fromisoformat(row['done_at'])
        return datetime.fromisoformat(row['done_at']).astimezone(now.tzinfo).date()
    completed=[r for r in leaves if (d:=completed_day(r)) is not None and first<=d<=last]
    activity={d for r in leaves if (d:=completed_day(r)) is not None}
    streak=0
    day=now.date() if now.date() in activity else now.date()-timedelta(days=1)
    while day in activity:
        streak+=1;day-=timedelta(days=1)
    days=[]
    day=first
    while day<=last:
        tasks=[r for r in planned if r['due'][:10]==day.isoformat()]
        days.append(dict(day=day.isoformat(),total=len(tasks),done=sum(r['done'] for r in tasks),
                         failed=sum(r.get('skipped',0) for r in tasks)))
        day+=timedelta(days=1)
    return dict(total=len(planned),done=sum(r['done'] for r in planned),
                failed=sum(r.get('skipped',0) for r in planned),
                pending=sum(not r['done'] and not r.get('skipped') for r in planned),
                completed=len(completed),streak=streak,days=days,
                important=sorted([r for r in completed if r['priority']],key=lambda r:r['done_at'],reverse=True),
                planned_minutes=sum(r['duration'] for r in planned),
                closed_minutes=sum(r['duration'] for r in planned if r['done']))
