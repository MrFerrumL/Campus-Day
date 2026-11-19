"""Calories and macros from a chat message, saved to the food diary only on a button.

«съел 200 г гречки и 2 яйца», «/kcal банан» or any message after the «Посчитать КБЖУ»
button gets a breakdown by the local food table. The counted meal waits under a short
token; «Записать» saves exactly that meal, «Не записывать» drops it.
"""
from datetime import datetime, timedelta
import re
from uuid import uuid4

from . import nutrition
from .wellness import Wellness

PENDING_KEY = 'food_counts'
WAIT_KEY = 'food_wait'
KEEP = 10                         # counted meals waiting for a button
PENDING_FOR = timedelta(days=1)   # a button older than this asks to count again
WAIT_FOR = timedelta(minutes=15)  # after «Посчитать КБЖУ» the next message is food
EXAMPLE = '«200 г гречки, 2 яйца и банан» или «на обед борщ и 2 куска хлеба»'
SOURCE = 'Цифры примерные: таблица продуктов (USDA и средние домашние рецепты).'


# «на ужин купить курицу» is a task for later, not a meal eaten.
NOT_EATEN = re.compile(r'(?<!\w)(?:купить|куплю|приготов\w*|заказать|сделать|напомни\w*|надо|нужно|план\w*|встреч\w*|бы|хочу|хотел\w*|буду|будет|завтра|послезавтра)(?!\w)|\d{1,2}:\d{2}', re.I)


def is_meal_message(text):
    """Starts like a meal («съел…», «на обед…», «сколько калорий в…») and names a known food."""
    clean = nutrition.normalize(text)
    if not nutrition.LEAD.match(clean) or NOT_EATEN.search(clean):
        return False
    return bool(nutrition.count(text)['items'])


def waiting(store, now):
    since = store.get(WAIT_KEY)
    return bool(since) and now - datetime.fromisoformat(since) < WAIT_FOR


async def ask(bot):
    bot.store.set(WAIT_KEY, bot.now().isoformat())
    await bot.reply('🧮 Напишите, что съели и сколько: ' + EXAMPLE + '.\nГраммы можно не писать — посчитаю обычную порцию.')


async def offer(bot, text):
    """Count the message and offer to save it."""
    now = bot.now()
    bot.store.set(WAIT_KEY, None)
    result = nutrition.count(text)
    if not result['items']:
        await bot.reply('Не нашёл продуктов в таблице. Напишите проще, например: ' + EXAMPLE + '.\n'
                        'Или запишите вручную: /food Смузи | 250 | 5 | 3 | 45')
        return
    token = uuid4().hex[:10]
    pending = {k: v for k, v in (bot.store.get(PENDING_KEY) or {}).items()
               if now - datetime.fromisoformat(v['at']) < PENDING_FOR}
    pending[token] = dict(name=nutrition.title(result), note=nutrition.describe(result)[:500], at=now.isoformat(),
                          **result['total'])
    bot.store.set(PENDING_KEY, dict(sorted(pending.items(), key=lambda kv: kv[1]['at'])[-KEEP:]))
    await bot.reply('🍽 ' + nutrition.describe(result) + '\n\n' + SOURCE, reply_markup={'inline_keyboard': [[
        {'text': '✅ Записать в дневник', 'callback_data': 'w:eat:' + token},
        {'text': '✖ Не записывать', 'callback_data': 'w:eatno:' + token}]]})


async def text_input(bot, text):
    """Handle a plain message if it is about food; False lets other handlers try."""
    now = bot.now()
    if is_meal_message(text):
        await offer(bot, text)
        return True
    if not waiting(bot.store, now):
        return False
    bot.store.set(WAIT_KEY, None)
    if NOT_EATEN.search(nutrition.normalize(text)) or not nutrition.count(text)['items']:
        return False  # not food after all: a task, a pupil or a question for the assistant
    await offer(bot, text)
    return True


async def button(bot, kind, token):
    now = bot.now()
    pending = bot.store.get(PENDING_KEY) or {}
    meal = pending.pop(token, None)
    bot.store.set(PENDING_KEY, pending)
    if kind == 'eatno':
        await bot.reply('Не записываю.')
        return
    if not meal or now - datetime.fromisoformat(meal['at']) >= PENDING_FOR:
        raise ValueError('Этот подсчёт устарел или уже записан. Напишите еду ещё раз.')
    journal = Wellness(bot.store, bot.config.timezone)
    journal.mutate('wellness-meal', dict(name=meal['name'], time=now.strftime('%H:%M'), note=meal['note'],
                                         **{k: meal[k] for k in ('calories', 'protein', 'fat', 'carbs')}), now)
    total = journal.overview(now=now)['summary']
    await bot.reply(f'✅ Записано: {meal["calories"]:g} ккал. За сегодня {total["calories"]:g} ккал · '
                    f'Б {total["protein"]:g} / Ж {total["fat"]:g} / У {total["carbs"]:g} г.')
