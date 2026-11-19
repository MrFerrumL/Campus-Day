"""Recipes in the Telegram chat: /recipes, categories, one recipe with its video, and saved links.

A message with a link and the word «рецепт» is saved to «Мои рецепты» at once; a bare
link to a video site gets a «Сохранить?» button, other links are left to other handlers.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from . import recipe_links, recipes
from .wellness import Wellness

OFFER_KEY = 'recipe_link_offers'
# A message is a saved link only when it is short: «рецепт https://… паста». Longer texts
# with a link are tasks, hackathons or questions for the assistant.
MAX_EXTRA_WORDS = 8
BARE_EXTRA_WORDS = 2
OFFER_FOR = timedelta(days=1)
KEEP_OFFERS = 10
SHOW_LINKS = 20
CATEGORIES = {'breakfast': '🥣 Завтраки', 'main': '🍲 Обед и ужин', 'snack': '🍎 Перекусы',
              'quick': '⚡ До 15 минут', 'protein': '💪 Много белка', 'mine': '📌 Мои ссылки'}


def keyboard(rows):
    return {'reply_markup': {'inline_keyboard': [[b for b in row if b] for row in rows if any(row)]}}


def app_button(bot):
    url = bot.mini_app_url()
    if not url.startswith('https://'):
        return None
    return {'text': 'Открыть в приложении', 'web_app': {'url': url + ('' if url.endswith('/') else '/') + '?tab=gym&section=recipes'}}


def valid(url):
    try:
        return recipe_links.clean_url(url) == url
    except ValueError:
        return False


def pick(category):
    every = recipes.catalog()
    if category == 'quick':
        return [r for r in every if r['minutes'] <= recipes.QUICK_MINUTES]
    if category == 'protein':
        return [r for r in every if r['protein'] >= recipes.HIGH_PROTEIN]
    return [r for r in every if r['meal'] == category]


async def menu(bot):
    saved = len(recipe_links.links(bot.store))
    text = (f'📖 РЕЦЕПТЫ\n\n{len(recipes.RECIPES)} простых рецептов с калориями и БЖУ на порцию и видео на YouTube.'
            f'\nВаших ссылок: {saved}. Пришлите ссылку со словом «рецепт» — сохраню её сюда.')
    names = list(CATEGORIES.items())
    rows = [[{'text': n, 'callback_data': 'w:rcat:' + k} for k, n in names[i:i + 2]] for i in range(0, len(names), 2)]
    await bot.reply(text, **keyboard(rows + [[app_button(bot)]]))


async def category(bot, key):
    if key == 'mine':
        saved = recipe_links.links(bot.store)
        if not saved:
            await bot.reply('Пока нет сохранённых ссылок. Пришлите, например: «рецепт https://youtu.be/…».')
            return
        rows = [[{'text': x['title'][:60], 'url': x['url']}] for x in saved[:SHOW_LINKS] if valid(x['url'])]
        more = f'\nПоказаны {SHOW_LINKS} последних — все в приложении.' if len(saved) > SHOW_LINKS else ''
        await bot.reply(f'📌 МОИ РЕЦЕПТЫ · {len(saved)}{more}', **keyboard(rows + [[app_button(bot)]]))
        return
    if key not in CATEGORIES:
        raise ValueError('Неизвестный раздел')
    chosen = pick(key)
    lines = [f'• {r["name"]} — {r["calories"]} ккал, Б {r["protein"]:g} г, {r["minutes"]} мин' for r in chosen]
    rows = [[{'text': r['name'][:60], 'callback_data': 'w:rec:' + r['id']}] for r in chosen]
    await bot.reply(CATEGORIES[key].upper() + '\nНа одну порцию:\n\n' + '\n'.join(lines), **keyboard(rows))


async def show(bot, uid):
    recipe = recipes.find(uid)
    if not recipe:
        raise ValueError('Рецепт не найден. /recipes — список.')
    await bot.reply(recipes.describe(recipe), **keyboard([
        [{'text': '▶ Видео на YouTube', 'url': recipe['video']}],
        [{'text': '🍽 Записать порцию', 'callback_data': 'w:receat:' + uid}]]))


async def eat(bot, uid):
    recipe = recipes.find(uid)
    if not recipe:
        raise ValueError('Рецепт не найден.')
    now = bot.now()
    journal = Wellness(bot.store, bot.config.timezone)
    journal.mutate('wellness-meal', dict(name=f'{recipe["name"]} · 1 порция', time=now.strftime('%H:%M'),
                                         note='Рецепт из каталога', **{k: recipe[k] for k in ('calories', 'protein', 'fat', 'carbs')}), now)
    total = journal.overview(now=now)['summary']
    await bot.reply(f'✅ Записано: {recipe["calories"]} ккал. За сегодня {total["calories"]:g} ккал.')


async def save(bot, url, title):
    entry = recipe_links.add(bot.store, url, title, bot.now())
    await bot.reply(f'📌 Сохранил в «Мои рецепты»: {entry["title"]}', **keyboard([
        [{'text': '▶ Открыть', 'url': entry['url']}, {'text': '🗑 Удалить', 'callback_data': 'w:rdel:' + entry['id']}],
        [app_button(bot)]]))


async def text_input(bot, text):
    """Save or offer to save a recipe link; False for messages without one."""
    found = recipe_links.from_message(text)
    if not found:
        return False
    url, title = found
    try:
        url = recipe_links.clean_url(url)
    except ValueError:
        return False
    extra = len(title.split())
    if recipe_links.RECIPE_WORD.search(text) and extra <= MAX_EXTRA_WORDS:
        await save(bot, url, title)
        return True
    if not recipe_links.is_video(url) or extra > BARE_EXTRA_WORDS:
        return False
    now = bot.now()
    offers = {k: v for k, v in (bot.store.get(OFFER_KEY) or {}).items() if now - datetime.fromisoformat(v['at']) < OFFER_FOR}
    token = uuid4().hex[:10]
    offers[token] = dict(url=url, title=title, at=now.isoformat())
    bot.store.set(OFFER_KEY, dict(sorted(offers.items(), key=lambda kv: kv[1]['at'])[-KEEP_OFFERS:]))
    await bot.reply(f'Сохранить ссылку с {recipe_links.site_of(url)} в «Мои рецепты»?', **keyboard([[
        {'text': '📌 Сохранить', 'callback_data': 'w:rsave:' + token}, {'text': 'Нет', 'callback_data': 'w:rno:' + token}]]))
    return True


async def button(bot, kind, value):
    if kind == 'rcat':
        await category(bot, value)
    elif kind == 'rec':
        await show(bot, value)
    elif kind == 'receat':
        await eat(bot, value)
    elif kind == 'rdel':
        recipe_links.remove(bot.store, value)
        await bot.reply('🗑 Ссылка удалена.')
    elif kind in ('rsave', 'rno'):
        offers = bot.store.get(OFFER_KEY) or {}
        offer = offers.get(value)
        if kind == 'rno':
            offers.pop(value, None)
            bot.store.set(OFFER_KEY, offers)
            await bot.reply('Хорошо, не сохраняю.')
            return
        if not offer:
            raise ValueError('Кнопка устарела. Пришлите ссылку ещё раз.')
        await save(bot, offer['url'], offer['title'])  # a failed save keeps the offer for another try
        offers.pop(value, None)
        bot.store.set(OFFER_KEY, offers)
