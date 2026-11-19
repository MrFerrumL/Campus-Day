"""Recipe links the person saves to watch later: YouTube, Rutube, VK, TikTok or any site.

Links are only stored and shown; the bot never opens or downloads them. A link must be
http(s) with a real host; the name defaults to the site.
"""
from datetime import datetime
import re
from urllib.parse import urlsplit
from uuid import uuid4

KEY = 'recipe_links'
LIMIT = 200
MAX_URL = 500
MAX_TITLE = 120
URL = re.compile(r'https?://[^\s<>"\']+', re.I)
# Characters Telegram refuses in a button URL; the chat regex already stops at them.
BAD_URL_CHARS = re.compile(r'[\s<>"\'\x00-\x1f\x7f]')
# The word «рецепт» (or «рецепты») on its own, not inside «рецептор».
RECIPE_WORD = re.compile(r'(?<![а-яё])рецепт(?:ы|ик)?(?![а-яё])', re.I)
LEAD_WORDS = re.compile(r'^\s*(?:(?:сохрани|добавь|запомни|в\s+рецепты|рецепт)(?![а-яё])[:\s-]*)+', re.I)
# Sites where a link is most likely a video; with them the bot offers to save without the word «рецепт».
VIDEO_HOSTS = ('youtube.com', 'youtu.be', 'rutube.ru', 'vk.com', 'vkvideo.ru', 'tiktok.com', 'instagram.com',
               'dzen.ru', 'pinterest.com', 'eda.ru', 'povar.ru', 'russianfood.com')
SITES = {'youtube.com': 'YouTube', 'youtu.be': 'YouTube', 'rutube.ru': 'Rutube', 'vk.com': 'VK', 'vkvideo.ru': 'VK Видео',
         'tiktok.com': 'TikTok', 'instagram.com': 'Instagram', 'dzen.ru': 'Дзен', 'eda.ru': 'Еда.ру', 'povar.ru': 'Повар.ру'}


def host_of(url):
    host = (urlsplit(url).hostname or '').lower()
    return host[4:] if host.startswith('www.') else host.removeprefix('m.')


def site_of(url):
    host = host_of(url)
    return next((name for domain, name in SITES.items() if host == domain or host.endswith('.' + domain)), host)


def is_video(url):
    host = host_of(url)
    return any(host == d or host.endswith('.' + d) for d in VIDEO_HOSTS)


def clean_url(url):
    url = str(url or '').strip().rstrip('.,);!?»')
    parts = urlsplit(url)
    if (len(url) > MAX_URL or BAD_URL_CHARS.search(url) or parts.scheme not in ('http', 'https')
            or not parts.hostname or '.' not in parts.hostname or parts.username or parts.password):
        raise ValueError('Нужна ссылка вида https://…')
    return url


def links(store):
    return list(store.get(KEY) or [])


def add(store, url, title='', now=None):
    """Save a link (or rename it if it is already saved); returns the saved entry."""
    url = clean_url(url)
    given = ' '.join(str(title or '').split())[:MAX_TITLE]
    saved = links(store)
    same = next((x for x in saved if x['url'] == url), None)
    if same:
        if given:  # a new name renames; a bare re-send keeps the old one
            same['title'] = given
            store.set(KEY, saved)
        return same
    title = given or f'Рецепт · {site_of(url)}'
    if len(saved) >= LIMIT:
        raise ValueError(f'Сохранено уже {LIMIT} ссылок. Удалите старые в приложении: Зал → Рецепты.')
    entry = dict(id=uuid4().hex[:10], url=url, title=title, site=site_of(url),
                 added=(now or datetime.now()).isoformat(timespec='minutes'))
    store.set(KEY, [entry] + saved)
    return entry


def remove(store, uid):
    saved = links(store)
    left = [x for x in saved if x['id'] != str(uid)]
    if len(left) == len(saved):
        raise ValueError('Эта ссылка уже удалена.')
    store.set(KEY, left)
    return dict(ok=True)


def from_message(text):
    """(url, title) when a chat message carries a link, else None; the title is the rest of the text."""
    found = URL.search(text or '')
    if not found:
        return None
    rest = ' '.join((text[:found.start()] + ' ' + text[found.end():]).split())
    return found.group(0), LEAD_WORDS.sub('', rest).strip(' -:—')
