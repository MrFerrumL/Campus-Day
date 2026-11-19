"""Authoritative payroll + future calendar income + explicit NET supplements.

A paired lesson is one teaching session and two pupil participations. Past
unreported slots are uncertain, never earned pay. All money is in kopecks.
"""
from datetime import date,datetime,timedelta
import json,re
from uuid import uuid4
from .income import DEFAULT_SHARE
from .tutoring import MONTHS,money,price

KEY='salary_extras'


def month_key(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}',value):raise ValueError('Месяц: ГГГГ-ММ')
    return date.fromisoformat(value+'-01').strftime('%Y-%m')


def extras(store,month=None):
    return [dict(e) for e in store.get(KEY,[]) if month is None or e['month']==month]


def add_extra(store,month,count,rub,note='',reference=None):
    """`rub` is the NET amount to add, not a pupil payment to halve."""
    month=month_key(month)
    if isinstance(count,bool) or not re.fullmatch(r'\d+',str(count).strip()):raise ValueError('Число занятий: от 1 до 100')
    count=int(count)
    if not 1<=count<=100:raise ValueError('Число занятий: от 1 до 100')
    if isinstance(rub,bool):raise ValueError('Укажите сумму доплаты в рублях')
    amount=price(str(rub));note=' '.join(str(note or 'Отработка').split())[:100]
    if reference is not None and (not isinstance(reference,str) or not 1<=len(reference)<=120):raise ValueError('Неверный идентификатор добавления')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE');saved=extras(store)
        previous=next((e for e in saved if reference and e.get('reference')==reference),None)
        if previous:return previous
        if len(saved)>=100:raise ValueError('Удалите старые доплаты перед добавлением новых')
        row=dict(id=uuid4().hex[:12],month=month,count=count,amount=amount,note=note,reference=reference)
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(KEY,json.dumps(saved+[row],ensure_ascii=False)))
    return row


def remove_extra(store,uid):
    with store.db:
        store.db.execute('BEGIN IMMEDIATE');saved=extras(store);left=[e for e in saved if e['id']!=uid]
        if len(left)==len(saved):raise ValueError('Эта доплата уже удалена')
        store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(KEY,json.dumps(left,ensure_ascii=False)))
    return dict(ok=True)


def slot(day,time,duration):return (day,time[:5],int(duration))


def report_lessons(store,month,shares):
    sessions,known=set(),set();amount=participations=unpaid=0;last=None
    for account in store.platform_accounts():
        uid=account['student_id'];share=shares.get(uid,store.get('tutoring_share',DEFAULT_SHARE));seen_ids=set()
        for lesson in account['lessons']:
            if not lesson['day'].startswith(month) or lesson['id'] in seen_ids:continue
            seen_ids.add(lesson['id']);block=slot(lesson['day'],lesson['time'],lesson['duration']);known.add((uid,*block))
            if lesson['status'] not in ('attended','makeup'):continue
            sessions.add(block);last=max(last or lesson['day'],lesson['day'])
            if not lesson['chargeable']:unpaid+=1;continue
            participations+=1;amount+=lesson['amount']*share//100
    return dict(count=len(sessions),participations=participations,amount=amount,unpaid=unpaid,last=last),known,sessions


def calendar_groups(rows,now,known,cutoff=None,linked=(),fallback=False):
    groups={k:dict(count=0,participations=0,amount=0,unknown=0,dates=[]) for k in ('upcoming','waiting','marked')}
    sessions={k:set() for k in groups}
    for row in rows:
        for lesson in row['dates']:
            start=datetime.fromisoformat(lesson['start']) if lesson.get('start') else datetime.fromisoformat(lesson['day']+'T'+lesson['time'][:5]).replace(tzinfo=now.tzinfo)
            end=datetime.fromisoformat(lesson['end']) if lesson.get('end') else start+timedelta(minutes=120)
            block=slot(lesson['day'],start.strftime('%H:%M'),round((end-start).total_seconds()/60))
            if (row['id'],*block) in known:continue
            if end>now:kind='upcoming'
            elif fallback and lesson['done']:kind='marked'
            elif cutoff and lesson['day']<cutoff and row['id'] in linked:continue
            else:kind='waiting'
            group=groups[kind];sessions[kind].add(block);group['participations']+=1
            if lesson['amount'] is None:group['unknown']+=1
            else:group['amount']+=lesson['amount']*row.get('share',DEFAULT_SHARE)//100
            group['dates'].append(dict(day=lesson['day'],time=lesson['time'],name=row['name'],amount=lesson['amount']))
    for key,group in groups.items():group['count']=len(sessions[key])
    return groups,sessions


def summary(store,rows,month,now):
    month=month_key(month);sync=store.get('reollity_sync') or {};shares={r['id']:r.get('share',DEFAULT_SHARE) for r in rows}
    done,known,done_sessions=report_lessons(store,month,shares);payroll=store.get('reollity_salary_reports',{}).get(month)
    source='payroll' if payroll else 'reollity_lessons' if sync.get('fetched') else 'calendar'
    groups,sets=calendar_groups(rows,now,known,cutoff=sync.get('cutoff'),linked=sync.get('student_ids',[]),fallback=source=='calendar')
    if source=='calendar':
        done=groups['marked']|dict(last=max((r['day'] for r in groups['marked']['dates']),default=None),unpaid=0);done_sessions=sets['marked']
    if payroll:done=dict(done,estimated_amount=done['amount'],amount=payroll['salary'])
    added=extras(store,month);extra=dict(count=sum(e['count'] for e in added),amount=sum(e['amount'] for e in added),items=added)
    future=groups['upcoming'];waiting=groups['waiting'];earned=done['amount']+extra['amount']
    return dict(month=month,source=source,synced=sync.get('fetched'),sync_error=sync.get('error'),payroll=payroll,
        payroll_error=store.get('reollity_salary_errors',{}).get(month),reported=done,waiting=waiting,upcoming=future,extras=extra,
        earned=earned,forecast=earned+future['amount'],forecast_count=len(done_sessions|sets['upcoming'])+extra['count'],
        conducted_count=len(done_sessions)+extra['count'],forecast_participations=done['participations']+future['participations'],
        unknown=future['unknown'],counts_mismatch=bool(payroll and payroll['participations']!=done['participations']),
        daily_report=store.get('salary_daily_report',False),report_time=store.get('salary_report_time','21:00'),
        potential_with_waiting=earned+future['amount']+waiting['amount'],refreshed=payroll.get('fetched') if payroll else sync.get('fetched'))


def text(s):
    year,month=map(int,s['month'].split('-'));r,u,e,w=s['reported'],s['upcoming'],s['extras'],s['waiting'];exact=s['source']=='payroll'
    lines=[f'💼 ЗАРПЛАТА · {MONTHS[month-1].upper()} {year}',
           f'✅ Проведено по Reollity: {r["count"]} зан. · {r["participations"]} ученико-занятий',
           ('По зарплатному отчёту Reollity: ' if exact else 'Расчётная доля за проведённые: ')+money(r['amount'])]
    for item in e['items']:lines.append(f'➕ {item["note"]}: {item["count"]} зан. · {money(item["amount"])} чистыми')
    lines+=['',f'💵 Уже заработано: {money(s["earned"])} · {s["conducted_count"]} зан. с отработками',
             f'📅 Осталось по графику: {u["count"]} зан. — {money(u["amount"])}',
             f'💰 Прогноз за месяц: {money(s["forecast"])}',f'Всего с доплатами: {s["forecast_count"]} зан.']
    if w['count']:lines.append(f'⏳ Прошедшие без отчёта: {w["count"]} занятий · {money(w["amount"])} — требуют проверки, в итог не включены.')
    if s['unknown']:lines.append(f'⚠️ У {s["unknown"]} будущих ученико-занятий нет цены; прогноз неполный.')
    if not exact:lines.append('⚠️ Зарплатный отчёт не получен: расчёт по занятиям не учитывает корректировки Reollity.')
    if s['counts_mismatch']:lines.append('⚠️ Число занятий в зарплатном отчёте и истории отличается. Сумма взята из самого зарплатного отчёта.')
    if s['sync_error'] or s['payroll_error']:lines.append('⚠️ Показаны последние доступные данные; сверка требует обновления.')
    if s['refreshed']:lines.append('Сверено: '+datetime.fromisoformat(s['refreshed']).strftime('%d.%m %H:%M МСК'))
    lines.append('Пара учеников — одно занятие, две оплаты. Прогноз предполагает проведение будущих занятий.')
    return lines[0]+'\n\n'+'\n'.join(lines[1:])


def payroll_text(s):
    p=s['payroll']
    if not p:return 'Зарплатный отчёт пока недоступен. Нажмите «Сверить».'
    return '\n'.join(['🧾 РАСЧЁТ REOLLITY · '+s['month'],'Общая сумма отчётов: '+money(p['total_all']),
        'Отчёты с опозданием: '+money(p['late_reports_amount']),'Доход, учтённый платформой: '+money(p['income_counted']),
        'Вычет за переводы (поле Reollity): '+money(p['bank_transfer_deduction']),'ВАША ЗАРПЛАТА ПО ПЛАТФОРМЕ: '+money(p['salary']),
        'Эта зарплата уже включает корректировки Reollity; вычет второй раз не применяется.'])
