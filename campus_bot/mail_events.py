"""Conservative opportunity briefs. Email text is data, never executable instructions."""
from datetime import datetime
from email.utils import parsedate_to_datetime
import re

MONTHS = ('январ','феврал','март','апрел','мая','июн','июл','август','сентябр','октябр','ноябр','декабр')
TOPICS = r'хакатон|hackathon|отбор|тестирован|стажиров|школ[ауы].{0,35}(?:аналит|данных|разработ)|обучени|образован|курс|экзамен|вебинар|митап'
PROMO = r'промокод|скидк|распродаж|купите|купи\s|чёрн[а-я]* пятниц|черн[а-я]* пятниц|акци[яию]'
PARTICIPATION = r'ваш[а-я]* заявк|вы зарегистрирован|ты зарегистрирован|отборочн|приглаш.{0,35}тест|принят[а-я]* на|мотивационн.{0,15}письм|сдать решени|сдач[аи] решени'
DATE = re.compile(r'(?<!\d)(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}))?|(\d{1,2})\s+('
                  + '|'.join(m+r'[а-я]*' for m in MONTHS) + r')(?:\s+(20\d{2}))?)(?!\d)', re.I)


def analyse(message, tz):
    from .mail import body_text
    subject = ' '.join(str(message.get('Subject','Письмо')).split())[:180]
    body = body_text(message, 10000)
    text = subject+'\n'+body
    if not re.search(TOPICS,text,re.I):
        return None
    if re.search(PROMO,text,re.I) and not re.search(PARTICIPATION,text,re.I):
        return None
    try:
        received = parsedate_to_datetime(str(message.get('Date'))).astimezone(tz)
    except (ValueError,TypeError,AttributeError):
        received = datetime.now(tz)
    candidates, seen, facts = [],set(),[]
    for match in DATE.finditer(body):
        try:
            a,b,c,d,e,f,g,h,i=match.groups()
            month = int(b or e) if b or e else next(n+1 for n,m in enumerate(MONTHS) if h.lower().startswith(m))
            year = int(a or f or i or received.year)
            if not (a or f or i) and received.month==12 and month==1:
                year+=1
            day = int(c or d or g)
            line_start=body.rfind('\n',0,match.start())+1
            line_end=body.find('\n',match.end())
            line=body[line_start:line_end if line_end>=0 else len(body)].strip()
            # Only an explicit time associated with this date is accepted automatically.
            following=body[match.end():min(len(body),match.end()+130)]
            next_date=DATE.search(following)
            if next_date:following=following[:next_date.start()]
            following=following.split('\n',1)[0]
            times=re.findall(r'(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)',following)
            value=times[-1] if times and (len(times)==1 or re.search(r'\bдо\b',following,re.I)) else None
            if re.search(r'UTC|GMT|по местному|екатеринбург|астан|алмат|новосибирск|владивосток',text,re.I):
                value=None
            base=datetime(year,month,day,tzinfo=tz)
            due=base.replace(hour=int(value.split(':')[0]),minute=int(value.split(':')[1])) if value else None
            key=(base.date().isoformat(),due.isoformat() if due else None)
            if key in seen:continue
            seen.add(key)
            facts.append(line[:280])
            candidates.append(dict(day=str(base.date()),due=due.isoformat() if due else None,
                                   title=subject,context=line[:1500]))
        except (ValueError,StopIteration,AttributeError):
            continue
    if not candidates:
        candidates=[dict(day=None,due=None,title=subject,context=body[:1500])]
    explicit_days={c['day'] for c in candidates if c.get('due')}
    candidates=[c for c in candidates if c.get('due') or c.get('day') not in explicit_days]
    summary='\n'.join(dict.fromkeys(facts))[:850] or body[:650]
    return dict(title=subject,summary=summary,candidates=candidates[:8])


async def add_from_mail(bot, data):
    _,_,key,index=data.split(':')
    index=int(index)
    offer=bot.store.mail_action(key)
    if not offer or not 0<=index<len(offer['candidates']):
        await bot.reply('Это письмо больше недоступно. Откройте исходное письмо.')
        return
    candidate=offer['candidates'][index]
    if candidate.get('task_id'):
        await bot.chat.task_card(candidate['task_id'])
        return
    if candidate.get('due'):
        due=datetime.fromisoformat(candidate['due'])
        if due<=bot.now():
            await bot.reply('Указанный в письме срок уже прошёл. Добавьте задачу с новым сроком через /add.')
            return
        uid=bot.store.accept_mail_task(key,index)
        await bot.reply('🚨 Важная задача добавлена. Напомню за 3 дня, сутки, 6 часов, 2 часа и в срок.')
        await bot.chat.task_card(uid)
        return
    values=dict(kind='task',title=candidate['title'],mail_action_id=key,mail_candidate=index,
                note=candidate.get('context',''),priority=1)
    if candidate.get('day'):
        values.update(step='time',day=candidate['day'])
        state=bot.chat.pending(**values)
        await bot.chat.ask_time(state)
    else:
        values.update(step='date',purpose='new',suggested_title=candidate['title'])
        bot.chat.pending(**values)
        await bot.reply('В письме нет однозначного срока. Напишите дату (например 05.11), затем выберем время. /cancel — отменить.')
