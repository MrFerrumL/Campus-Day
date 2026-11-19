"""Steps and activity in the Telegram chat.

/steps 10000, /activity бег 5 км 30 мин and /weight 105 178 write at once. A plain message
such as «пробежал 5 км за 30 минут» or «прошёл 10 тыс шагов» gets the burn and a
«Записать» button, so a passing remark never lands in the diary by itself.
"""
from datetime import datetime, timedelta
import re
from uuid import uuid4

from . import activity
from .wellness import Wellness

PENDING_KEY = 'activity_offers'
KEEP = 10
PENDING_FOR = timedelta(days=1)
LEAD = re.compile(r'^\s*(?:я\s+)?(?:прош[её]л|прошла|пробежал[аи]?|бегал[аи]?|проплыл[аи]?|плавал[аи]?|проехал[аи]?|'
                  r'занимал\w*|позанимал\w*|тренировал\w*|потренировал\w*|был\w*\s+в\s+зале|сходил\w*\s+в\s+зал|'
                  r'сделал\w*|отходил\w*|гулял\w*|погулял\w*|шаги|шагов|бег|гребля|йога|растяжка)(?![а-я])', re.I)
NOT_DONE = re.compile(r'(?<![а-я])(?:надо|нужно|буду|будет|завтра|послезавтра|хочу|план\w*|напомни\w*|бы|'
                      r'конспект\w*|лаб\w*|дз|домашк\w*|курс\w*|задач\w*|тест\w*)(?![а-я])', re.I)
HINT = 'Примеры: /steps 10000 · /activity бег 5 км 30 мин · /activity зал 1,5 часа · /weight 105 178'


def journal(bot):
    return Wellness(bot.store, bot.config.timezone)


def weight_note(bot):
    settings = bot.store.get('wellness_settings', {}) or {}
    return '' if settings.get('weight_kg') else '\nУкажите вес, чтобы считать расход: /weight 105 178 (вес и рост).'


def day_line(bot, now):
    s = journal(bot).overview(now=now)
    a = s['activity']
    if a['burned'] is None:
        return ''
    return f'\nЗа сегодня потрачено {a["burned"]} ккал активностью; съедено {s["summary"]["calories"]:g} ккал.'


async def save(bot, parsed, now, note=''):
    j = journal(bot)
    if 'steps' in parsed:
        before = next((r['steps'] for r in j.rows('steps') if r['day'] == now.date().isoformat()), None)
        row = j.mutate('wellness-steps', dict(steps=parsed['steps']), now)
        kcal = f', {row["kcal"]} ккал' if row['kcal'] is not None else ''
        was = f' Было {before} — шагомер считает за весь день, поэтому число заменяется.' if before and before != row['steps'] else ''
        await bot.reply(f'👣 Шаги за сегодня: {row["steps"]} (≈ {row["km"]:g} км{kcal}).{was}' + weight_note(bot) + day_line(bot, now))
        return
    row = j.mutate('wellness-activity', dict(type=parsed['type'], minutes=parsed['minutes'],
                                            distance_km=parsed.get('distance_km'), note=note), now)
    await bot.reply('🔥 Записано: ' + activity.describe(row) + '.' + weight_note(bot) + day_line(bot, now))


async def command(bot, cmd, args):
    now = bot.now()
    try:
        if cmd == '/weight':
            parts = args.replace(',', '.').split()
            if not 1 <= len(parts) <= 2:
                raise ValueError('Пример: /weight 105 178 — вес в кг и рост в см.')
            body = dict(weight_kg=parts[0], **({'height_cm': parts[1]} if len(parts) == 2 else {}))
            journal(bot).mutate('wellness-settings', body, now)
            await bot.reply(f'⚖️ Сохранено: {parts[0]} кг' + (f', {parts[1]} см' if len(parts) == 2 else '') + '. Расход теперь считается по этому весу.')
            return
        if cmd == '/steps':
            if not args:
                raise ValueError('Пример: /steps 10000')
            parsed = activity.parse(args + ' шагов')
            if not parsed:
                raise ValueError('Пример: /steps 10000')
            await save(bot, parsed, now)
            return
        parsed = activity.parse(args) if args else None
        if not parsed:
            names = ', '.join(v[0].lower() for v in activity.TYPES.values())
            raise ValueError(f'Не понял. {HINT}\nВиды: {names}.')
        await save(bot, parsed, now)
    except ValueError as exc:
        await bot.reply(str(exc))


async def text_input(bot, text):
    """Offer to log a plain message about activity; False for anything else."""
    if not LEAD.search(text) or NOT_DONE.search(text):
        return False
    parsed = activity.parse(text)
    if not parsed:
        return False
    now = bot.now()
    offers = {k: v for k, v in (bot.store.get(PENDING_KEY) or {}).items() if now - datetime.fromisoformat(v['at']) < PENDING_FOR}
    token = uuid4().hex[:10]
    offers[token] = dict(parsed, at=now.isoformat(), note=text[:200])
    bot.store.set(PENDING_KEY, dict(sorted(offers.items(), key=lambda kv: kv[1]['at'])[-KEEP:]))
    settings = bot.store.get('wellness_settings', {}) or {}
    weight, height = settings.get('weight_kg'), settings.get('height_cm')
    if 'steps' in parsed:
        kcal = activity.steps_kcal(parsed['steps'], weight, height)
        text_out = f'👣 {parsed["steps"]} шагов ≈ {activity.steps_km(parsed["steps"], height):g} км'
    else:
        met = activity.met_for(parsed['type'], parsed['minutes'], parsed.get('distance_km'))
        kcal = activity.active_kcal(met, weight, parsed['minutes'])
        text_out = '🔥 ' + activity.describe(dict(parsed, name=activity.TYPES[parsed['type']][0], kcal=None))
    text_out += f' — {kcal} ккал.' if kcal is not None else '.'
    await bot.reply(text_out + weight_note(bot), reply_markup={'inline_keyboard': [[
        {'text': '✅ Записать', 'callback_data': 'w:act:' + token}, {'text': '✖ Нет', 'callback_data': 'w:actno:' + token}]]})
    return True


async def button(bot, kind, token):
    offers = bot.store.get(PENDING_KEY) or {}
    offer = offers.pop(token, None)
    bot.store.set(PENDING_KEY, offers)
    if kind == 'actno':
        await bot.reply('Не записываю.')
        return
    now = bot.now()
    if not offer or now - datetime.fromisoformat(offer['at']) >= PENDING_FOR:
        raise ValueError('Кнопка устарела. Напишите ещё раз.')
    parsed = {k: offer[k] for k in ('steps', 'type', 'minutes', 'distance_km') if k in offer}
    # Logged for the moment it was written, not when the button was pressed.
    await save(bot, parsed, datetime.fromisoformat(offer['at']), note=offer.get('note', '') if 'type' in parsed else '')
