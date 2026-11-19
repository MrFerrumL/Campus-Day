"""Local parsing of dated checklists; no task text is sent to an AI provider."""
from datetime import datetime, timedelta
import re

from .models import at, parse_day

HEADER = re.compile(r'^(?:план|задачи|отч[её]т|список\s+дел)(?:\s+(?:на|за))?\s+(.+?)\s*:?$',re.I)
PRIORITY = re.compile(r'^\s*(?:важно\s*:|[!‼]|🚨)\s*',re.I)
NUMBER = re.compile(r'^(\s*)(?:(\d{1,2})[.)]\s*|[-•]\s+)?(.*?)\s*$')
RANGE = re.compile(r'(?:с\s*)?(\d{1,2}:\d{2})\s*(?:[-–—]|до)\s*(\d{1,2}:\d{2})',re.I)
CLOCK = re.compile(r'(?:\bв\s+|^)(\d{1,2}:\d{2})\b',re.I)
PAST = re.compile(r'^(?:уже\s+)?(?:написал[аи]?|сделал[аи]?|сдал[аи]?|выполнил[аи]?|закончил[аи]?|пров[её]л[аи]?|прочитал[аи]?|решил[аи]?|отправил[аи]?|собрал[аи]?|помыл[аи]?|постирал[аи]?)\b',re.I)


# The first word of a task phrased as an action: «собрать», «помыть», «отвезти», «испечь», «записаться».
INFINITIVE=re.compile(r'^[а-яё]+(?:ть|ти|чь)(?:ся|сь)?$',re.I)


def priority_text(text):
    match=PRIORITY.match(text)
    return (text[match.end():].strip(),1) if match else (text.strip(),0)


def task_status(row):
    return 'done' if row['done'] else 'failed' if row.get('skipped') else 'pending'


def task_when(row):
    due=datetime.fromisoformat(row['due'])
    if row.get('all_day'):
        return f'{due:%d.%m} · без времени'
    if row.get('duration'):
        start=due-timedelta(minutes=row['duration'])
        return f'{start:%H:%M}–{due:%H:%M}'
    return f'{due:%d.%m · %H:%M}'


def parse_plan(text, today, tz):
    lines=[line.rstrip() for line in text.replace('\t','    ').splitlines() if line.strip()]
    if not lines:
        return None
    head=HEADER.fullmatch(lines[0].strip())
    if head:
        day=parse_day(head[1].strip().rstrip(':').strip(),today)
        lines=lines[1:]
    elif PRIORITY.match(lines[0]) and len(lines)==1:
        day=today
    else:
        return None
    if not lines:
        raise ValueError('После даты напишите задачи, по одной на строку.')
    if len(lines)>60:
        raise ValueError('За раз можно добавить до 60 пунктов.')
    nodes=[]
    stack=[]
    virtual=None
    last_virtual_number=0
    for line in lines:
        match=NUMBER.fullmatch(line)
        indent=len(match[1]);number=int(match[2]) if match[2] else None
        raw=match[3].strip()
        if not raw:
            continue
        while stack and stack[-1][0]>=indent:
            stack.pop()
        parent=stack[-1][1] if stack else None
        previous=nodes[-1] if nodes else None
        if parent is None and previous and previous['title'].endswith(':') and virtual is None:
            virtual=len(nodes)-1
            last_virtual_number=0
        if parent is None and previous and number==1 and previous.get('_number',0)>1:
            if previous['title'].endswith(':') or re.search(r'вечер|дела|собрать|сделать|подготовка',previous['title'],re.I):
                virtual=len(nodes)-1
                last_virtual_number=0
        if parent is None and virtual is not None:
            if number is not None and number>last_virtual_number+1:
                virtual=None
            else:
                parent=virtual
                last_virtual_number=number or last_virtual_number
        name,priority=priority_text(raw)
        done=bool(re.match(r'^(?:✅|\[[xхXХ]\])\s*',name))
        name=re.sub(r'^(?:✅|\[[xхXХ]\]|\[\s*\])\s*','',name)
        name,extra_priority=priority_text(name)
        priority=max(priority,extra_priority)
        done=done or bool(PAST.match(name))
        period='вечером' if re.search(r'\bвечер(?:ом|ние)?\b',name,re.I) else ''
        note='Вечером; точное время не указано.' if period else ''
        duration=0;all_day=True;due=at(day,'23:59',tz)
        time_range=RANGE.search(name)
        if time_range:
            start=at(day,time_range[1],tz);end=at(day,time_range[2],tz)
            duration=int((end-start).total_seconds()/60)
            if not 5<=duration<=1440:
                raise ValueError('Проверьте интервал времени: окончание должно быть позже начала в этот же день.')
            due=end;all_day=False
            name=(name[:time_range.start()]+name[time_range.end():]).strip(' ,—–-')
        else:
            clock=CLOCK.search(name)
            if clock:
                due=at(day,clock[1],tz);all_day=False
                name=(name[:clock.start()]+name[clock.end():]).strip(' ,—–-')
        if parent is not None:
            priority=max(priority,nodes[parent]['priority'])
            if not note:
                note=nodes[parent].get('note','')
        if not 1<=len(name)<=300:
            raise ValueError('Название задачи должно быть от 1 до 300 символов.')
        nodes.append(dict(title=name,due=due.isoformat(),duration=duration,all_day=all_day,
                          priority=priority,done=done,parent=parent,note=note,_number=number or 0))
        stack.append((indent,len(nodes)-1))
    parents={n['parent'] for n in nodes if n['parent'] is not None}
    for i,node in enumerate(nodes):
        node.pop('_number')
        node['is_group']=i in parents
        if node['is_group']:
            node['title']=node['title'].rstrip(':').strip()
            node.update(duration=0,all_day=True,due=at(day,'23:59',tz).isoformat(),done=False)
        # «вечером собрать: шкаф, стойку» — the group's verb completes subtasks that have none.
        if node['parent'] is not None:
            verb=nodes[node['parent']]['title'].rstrip(':').split()[-1:]
            if verb and INFINITIVE.match(verb[0]) and not INFINITIVE.match(node['title'].split()[0]):
                node['title']=verb[0].capitalize()+' '+node['title']
    if not nodes:
        raise ValueError('Не нашёл задач после даты.')
    return dict(day=day.isoformat(),nodes=nodes)


class DailyPlans:
    def __init__(self,bot):
        self.bot,self.store=bot,bot.store

    async def handle_text(self,text):
        if not text.strip():
            return False
        if not (HEADER.match(text.splitlines()[0]) or PRIORITY.match(text)):
            return False
        if PRIORITY.match(text) and self.bot.chat.state():
            return False
        try:
            draft=parse_plan(text,self.bot.now().date(),self.bot.config.timezone)
            if draft is None:
                return False
            uid,created=self.store.import_daily_plan(draft,self.bot.now())
        except (ValueError,TypeError) as exc:
            await self.bot.reply(str(exc)+'\nПример: «План на завтра:\n1) Важно: сдать работу\n2) Помыть посуду».')
            return True
        self.store.set('chat_pending',None)
        await self.show(draft['day'],notice='✅ План сохранён.' if created else 'Этот план уже сохранён — дубликатов нет.',batch=uid)
        return True

    async def show(self,day,message=None,notice='',batch=None,page=1):
        rows=[r for r in self.store.items('task',include_done=True) if r['due'][:10]==str(day)]
        by_id={r['id']:r for r in rows}
        children={}
        for row in rows:
            parent=row['parent_id'] if row['parent_id'] in by_id else None
            children.setdefault(parent,[]).append(row)
        leaves=[r for r in rows if not r['is_group']]
        done=sum(r['done'] for r in leaves);failed=sum(r['skipped'] for r in leaves)
        lines=[f'📋 ПЛАН · {str(day)[8:10]}.{str(day)[5:7]}.{str(day)[:4]}']
        if notice:lines.append(notice)
        lines.append(f'✅ {done} · ❌ {failed} · ▫️ {len(leaves)-done-failed} в работе')
        buttons=[]
        icons={'done':'✅','failed':'❌','pending':'▫️'}
        ordered=[]
        def order(parent,depth=0):
            for row in children.get(parent,[]):
                ordered.append((row,depth))
                order(row['id'],depth+1)
        order(None)
        pages=max(1,(len(ordered)+19)//20)
        page=max(1,min(page,pages))
        visible={r['id'] for r,_ in ordered[(page-1)*20:page*20]}
        def visit(parent,depth=0):
            for row in children.get(parent,[]):
                if row['id'] not in visible:
                    visit(row['id'],depth+1)
                    continue
                status=task_status(row)
                group='▾ ' if row['is_group'] else ''
                important='🚨 Важно · ' if row['priority'] else ''
                line='  '*min(depth,5)+icons[status]+' '+group+important+row['title']
                if not row['is_group'] and not row['all_day']:
                    line+=' · '+task_when(row)
                lines.append(line)
                buttons.append([
                    {'text':('↩ ' if row['done'] else '✅ ')+row['title'][:25],
                     'callback_data':f'dp:status:{row["id"]}:{"pending" if row["done"] else "done"}:{page}'},
                    {'text':'↩' if row['skipped'] else '❌','callback_data':f'dp:status:{row["id"]}:{"pending" if row["skipped"] else "failed"}:{page}'},
                    {'text':'🚨' if row['priority'] else '☆','callback_data':f'dp:priority:{row["id"]}:{0 if row["priority"] else 1}:{page}'}])
                visit(row['id'],depth+1)
        visit(None)
        if not rows:lines.append('Пока ничего не запланировано.')
        lines.append('Без времени — задача на день. ✅ и ❌ можно отменить; группа отмечает все подпункты.')
        if batch:buttons.append([{'text':'Удалить это добавление','callback_data':'dp:undo:'+batch}])
        if pages>1:
            lines.append(f'Страница {page}/{pages}')
            buttons.append([{'text':'‹','callback_data':f'dp:view:{day}:{max(1,page-1)}'},
                            {'text':'›','callback_data':f'dp:view:{day}:{min(pages,page+1)}'}])
        buttons.append([{'text':'📊 Аналитика дня','callback_data':'c:stats:day:'+str(day)},
                        {'text':'📅 Расписание','callback_data':'c:day:'+str(day)}])
        await self.bot.chat.screen('\n\n'.join(lines[:3])+'\n\n'+'\n'.join(lines[3:]),{'inline_keyboard':buttons},message)

    async def callback(self,data,message):
        parts=data.split(':');action=parts[1]
        if action=='undo':
            row=self.store.db.execute('SELECT day FROM daily_plans WHERE id=?',(parts[2],)).fetchone()
            if row:
                self.store.undo_daily_plan(parts[2])
                await self.show(row[0],message,'Добавление удалено.')
            return
        if action=='view':
            await self.show(parts[2],message,page=int(parts[3]) if len(parts)>3 else 1)
            return
        row=self.store.db.execute("SELECT * FROM items WHERE id=? AND kind='task'",(int(parts[2]),)).fetchone()
        if row is None:
            await self.bot.reply('Задача уже удалена.')
            return
        if action=='status':
            self.store.set_task_status(row['id'],parts[3],self.bot.now())
        elif action=='priority' and parts[3] in ('0','1'):
            self.store.set_priority(row['id'],int(parts[3]))
        else:
            raise ValueError('Неизвестное действие')
        await self.show(row['due'][:10],message,page=int(parts[4]) if len(parts)>4 else 1)
