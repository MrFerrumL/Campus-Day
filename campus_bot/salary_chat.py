"""Salary cards in chat. Slow Reollity reads run in the background."""
from datetime import date,datetime,timedelta
import re
from . import salary
from .models import clock,at

STALE_AFTER=timedelta(minutes=15)
ADD=re.compile(r'^\+\s*(\d+)\s+(\d+(?:[.,]\d{1,2})?)\s*(?:₽|руб\.?|р\.?)?\s*(.*)$',re.I)
HELP='Доплата чистыми: /zp + 3 5400 отработки. Месяц: /zp 2026-11.'


def month_of(value,today):
    if not value:return today.replace(day=1)
    if re.fullmatch(r'\d{2}\.\d{4}',value):value=value[3:]+'-'+value[:2]
    return date.fromisoformat(salary.month_key(value)+'-01')


def state(bot,month):
    from .reollity import billing_state
    return billing_state(bot.store,bot.schedule,month,now=bot.now())['salary']


def keyboard(bot,s,month):
    previous=(month-timedelta(days=1)).replace(day=1);following=(month.replace(day=28)+timedelta(days=4)).replace(day=1);key=month.strftime('%Y-%m')
    rows=[[{'text':'‹ '+previous.strftime('%m.%Y'),'callback_data':'zp:m:'+previous.strftime('%Y-%m')},
           {'text':following.strftime('%m.%Y')+' ›','callback_data':'zp:m:'+following.strftime('%Y-%m')}],
          [{'text':'🔄 Сверить и пересчитать','callback_data':'zp:sync:'+key},{'text':'🧾 Расчёт Reollity','callback_data':'zp:details:'+key}],
          [{'text':'🔔 Ежедневно: '+('вкл' if bot.store.get('salary_daily_report',False) else 'выкл'),'callback_data':'zp:auto:'+key}]]
    rows += [[{'text':'✖ '+e['note'][:20]+' · '+str(e['count'])+' зан.','callback_data':'zp:del:'+key+':'+e['id']}] for e in s['extras']['items']]
    return {'inline_keyboard':rows}


def stale(bot,month):
    report=bot.store.get('reollity_salary_reports',{}).get(month.strftime('%Y-%m'));fetched=(report or {}).get('fetched')
    return not fetched or bot.now()-datetime.fromisoformat(fetched)>STALE_AFTER


async def show(bot,month,message=None,note=''):
    s=state(bot,month);text=salary.text(s)
    if note:text+='\n\n'+note
    if bot.store.get('salary_daily_report',False):text+='\nЕжедневная сводка: '+bot.store.get('salary_report_time','21:00')+' МСК.'
    await bot.chat.screen(text+'\n\n'+HELP,keyboard(bot,s,month),message)


async def refresh(bot,month):
    service=bot.reollity
    if not service.configured:
        await show(bot,month,note='Reollity пока не подключена.');return
    active=getattr(service,'background_task',None)
    if service.lock.locked() or (active and not active.done()):
        await show(bot,month,note='🔄 Сверка уже идёт. После её окончания повторите /zp.');return
    requests=bot.store.get('salary_month_requests',[])
    bot.store.set('salary_month_requests',list(dict.fromkeys([month.strftime('%Y-%m')]+requests))[:4])
    async def update():
        meta=await service.refresh(force=True)
        await show(bot,month,note='' if meta else '⚠️ Обновить сверку не удалось. Показаны последние сохранённые данные.')
    service.background_task=bot.background(update())
    await bot.reply('🔄 Читаю зарплатный отчёт и занятия Reollity. Пришлю пересчитанную зарплату; остальные команды доступны.')


async def command(bot,args):
    try:
        month=bot.now().date().replace(day=1);args=args.strip()
        if args.lower().startswith('время '):
            value=clock(args.split(' ',1)[1]);bot.store.set('salary_report_time',value);bot.store.set('salary_daily_report',True)
            await show(bot,month,note='Ежедневная сводка установлена на '+value+' МСК.');return
        if args.lower() in ('sync','сверить'):await refresh(bot,month);return
        found=ADD.fullmatch(args)
        if found:
            count,rub,note=found.groups();salary.add_extra(bot.store,month.strftime('%Y-%m'),count,rub,note)
            await show(bot,month,note='Доплата сохранена целиком, без повторного деления на 50%.');return
        month=month_of(args,bot.now().date())
        if bot.reollity.configured and stale(bot,month):await refresh(bot,month)
        else:await show(bot,month)
    except (ValueError,TypeError) as exc:await bot.reply(str(exc))


async def callback(bot,data,message=None):
    try:
        _,action,value,*rest=data.split(':');month=month_of(value,bot.now().date())
        if action=='m':
            if bot.reollity.configured and stale(bot,month):await refresh(bot,month)
            else:await show(bot,month,message)
        elif action=='sync':await refresh(bot,month)
        elif action=='details':
            s=state(bot,month)
            await bot.chat.screen(salary.payroll_text(s),{'inline_keyboard':[[{'text':'‹ Зарплата','callback_data':'zp:m:'+value}]]},message)
        elif action=='del':salary.remove_extra(bot.store,rest[0]);await show(bot,month,message)
        elif action=='auto':
            bot.store.set('salary_daily_report',not bot.store.get('salary_daily_report',False));await show(bot,month,message)
        else:raise ValueError('Кнопка устарела. Откройте /zp.')
    except (ValueError,IndexError,TypeError) as exc:await bot.reply(str(exc))


async def daily(bot,now):
    """Wait briefly for fresh data without blocking reminders or sending a stale total as fresh."""
    if not bot.store.get('salary_daily_report',False):return
    due=at(now.date(),bot.store.get('salary_report_time','21:00'),bot.config.timezone)
    key='salary-daily:'+str(now.date())
    if not timedelta(0)<=now-due<=timedelta(hours=1) or bot.store.delivered(key):return
    month=now.date().replace(day=1)
    if bot.reollity.configured and stale(bot,month) and now-due<timedelta(minutes=10):
        bot.store.set('reollity_refresh_requested',True)
        return
    async def make_text():
        note='\n⚠️ Свежую сверку пока получить не удалось; показаны сохранённые данные.' if bot.reollity.configured and stale(bot,month) else ''
        return salary.text(state(bot,month))+note+'\n\n/zp — сверить и открыть подробности.'
    await bot.scheduler.deliver(key,due,now,make_text,grace=60)
