"""Calories and macros from a plain message: «200 г гречки, 2 яйца и банан».

The message is split into items; each item gets an amount (grams, millilitres, pieces,
spoons, glasses, portions or nothing) and the most specific food from `food_table`.
Everything is local, so it works without an AI key. Items it does not recognise are
returned as unknown instead of being guessed.
"""
import re

from .food_table import FOODS, SPOON

MAX_TEXT = 1000
MAX_ITEMS = 20
MAX_GRAMS = 5000

WORD_NUMBERS = {'один': 1, 'одна': 1, 'одно': 1, 'одну': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4,
                'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10,
                'пара': 2, 'пару': 2, 'половина': 0.5, 'половину': 0.5, 'пол': 0.5, 'полтора': 1.5, 'полторы': 1.5}

# What a meal message often starts with; it is not part of any food.
LEAD = re.compile(r'^\s*(?:я\s+)?(?:съел[аи]?|съем|поел[аи]?|ел[аи]?|скушал[аи]?|выпил[аи]?|покушал[аи]?|перекусил[аи]?|'
                  r'посчитай(?:те)?|сколько\s+(?:калорий|ккал)(?:\s+в)?|кбжу|ккал|калории|'
                  r'на\s+(?:завтрак|обед|ужин|перекус|полдник)\b|(?:завтрак|обед|ужин|перекус|полдник)\s*:)(?=[\s:,.!?]|$)[\s:-]*', re.I)

UNIT = (r'(?P<unit>кг|килограмм\w*|кило|г|гр|грамм\w*|мл|миллилитр\w*|л|литр\w*|шт(?:ук\w*|\.)?|'
        r'ст\.?\s?л\.?|столов\w*\s+лож(?:к|ек)\w*|ч\.?\s?л\.?|чайн\w*\s+лож(?:к|ек)\w*|лож(?:к|ек)\w*|'
        r'стакан\w*|чашк\w*|кружк\w*|кусок|куска|куски|кусков|кусочек|кусочк\w*|ломтик\w*|долек|дольк\w*|порци\w*|тарелк\w*|'
        r'скуп\w*|мерн\w*|бутылк\w*|банк\w*|пачк\w*|плитк\w*)')
AMOUNT = re.compile(r'(?<![\w.])(?P<num>\d+(?:\.\d+)?)?\s*(?:[xх×*]\s*)?' + UNIT + r'(?![\w])|'
                    r'(?<![\w.])(?:[xх×*]\s*)?(?P<bare>\d+(?:\.\d+)?)(?![\w.])', re.I)
SPLIT = re.compile(r'\s*(?:[,;+\n]|\s(?:и|а\s+также|плюс)\s)\s*', re.I)
WITH = re.compile(r'\s(?:с|со)\s', re.I)
WORD = re.compile(r'[a-zа-я0-9.]+')


def normalize(text):
    text = text.lower().replace('ё', 'е').replace('–', ' ').replace('—', ' ').replace('-', ' ')
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%', lambda m: ' pct' + m.group(1).split('.')[0] + ' ', text)
    text = re.sub(r'\bпол(?=стакан|ложк|банан|яблок|порци|тарелк|литр|кило|батон|булк|пачк|плитк|шоколад|грейпфрут|авокадо)', 'пол ', text)
    words = text.split(' ')
    return ' '.join(str(WORD_NUMBERS[w]) if w in WORD_NUMBERS else w for w in words)


def _stems():
    table = []
    for index, (stems, name, kcal, protein, fat, carbs, piece, portion) in enumerate(FOODS):
        for way in stems.split('|'):
            parts = way.split()
            table.append((parts, (len(parts), sum(map(len, parts)), -index), dict(
                name=name, kcal=kcal, protein=protein, fat=fat, carbs=carbs, piece=piece, portion=portion)))
    return table


STEMS = _stems()
FOOD_BY_NAME = {food['name']: food for _, _, food in STEMS}
# Grains are usually weighed dry: up to this many grams means the dry product.
DRY = {'Гречка варёная': 'Гречка сухая', 'Рис варёный': 'Рис сухой',
       'Овсянка на воде': 'Овсяные хлопья сухие', 'Макароны варёные': 'Макароны сухие'}
DRY_UP_TO = 90


def match(words):
    """The most specific food whose stems all start some word, with the indexes of those words."""
    best = None
    for parts, score, food in STEMS:
        used = []
        for stem in parts:
            hit = next((i for i, w in enumerate(words) if w.startswith(stem) and i not in used), None)
            if hit is None:
                break
            used.append(hit)
        else:
            if best is None or score > best[0]:
                best = (score, food, used)
    return (best[1], best[2]) if best else (None, [])


def unit_grams(unit, food):
    """Grams in one unit of this food, or None for a count of pieces/portions."""
    u = unit.lower().replace(' ', '')
    big, small = SPOON.get(food['name'], (15, 5))
    if u.startswith(('кг', 'кило')):
        return 1000
    if u.startswith(('мл', 'миллилитр')) or u in ('г', 'гр') or u.startswith('грамм'):
        return 1
    if u == 'л' or u.startswith('литр'):
        return 1000
    if u.startswith(('ст.', 'стл', 'столов')):
        return big
    if u.startswith(('ч.', 'чл', 'чайн')):
        return small
    if u.startswith(('ложк', 'ложек')):
        return small if food['name'] in ('Сахар', 'Мёд') else big
    if u.startswith(('стакан', 'чашк', 'кружк')):
        return 250
    if u.startswith(('скуп', 'мерн')):
        return 30
    if u.startswith('бутылк'):
        return 500
    if u.startswith('банк'):
        return 330 if food['portion'] >= 250 else 185
    if u.startswith(('пачк', 'плитк')):
        return 100 if food['name'].startswith('Шоколад') else 200
    if u.startswith(('кус', 'ломтик', 'долек', 'дольк')):
        return food['piece'] or 30
    if u.startswith(('порци', 'тарелк')):
        return food['portion']
    return None  # шт: pieces


def amount(text):
    """(number, unit or None, text without the amount); number None if nothing was said."""
    found = AMOUNT.search(text)
    if not found:
        return None, None, text
    rest = (text[:found.start()] + ' ' + text[found.end():]).strip()
    if found.group('bare'):
        return float(found.group('bare')), None, rest
    return float(found.group('num') or 1), found.group('unit'), rest


def grams_for(number, unit, food):
    """Grams eaten and how the amount reads back to the person."""
    if number is None:
        return food['portion'], '1 шт' if food['piece'] == food['portion'] else 'порция'
    if unit is None:
        if number >= 30:
            return number, f'{number:g} г'
        if food['piece']:
            return number * food['piece'], f'{number:g} шт'
        return number * food['portion'], f'{number:g} порц.'
    per = unit_grams(unit, food)
    if per is None:
        return number * (food['piece'] or food['portion']), f'{number:g} шт'
    grams = number * per
    u = unit.lower()
    if u == 'л' or u.startswith(('мл', 'миллилитр', 'литр')):
        return grams, f'{grams:g} мл'
    if per == 1 or u.startswith(('кг', 'кило')):
        return grams, f'{grams:g} г'
    return grams, f'{number:g} {unit} ({grams:g} г)'


def items(text):
    """Split into separate foods; «кофе с молоком» stays whole, «гречка с курицей» becomes two."""
    out = []
    for chunk in SPLIT.split(text):
        chunk = chunk.strip(' .!?')
        if not chunk:
            continue
        parts = WITH.split(chunk)
        if len(parts) > 1:
            words, owner = [], []
            for side, part in enumerate(parts):
                found = WORD.findall(amount(part)[2])
                words += found
                owner += [side] * len(found)
            food, used = match(words)
            sides = {owner[u] for u in used}
            if not (food and len(sides) > 1):
                out.extend(p.strip(' .!?') for p in parts if p.strip(' .!?'))
                continue
        out.append(chunk)
    return out


def count(text):
    """Every item with grams and macros, the unknown ones, and the totals."""
    text = normalize(str(text)[:MAX_TEXT])
    text = LEAD.sub('', text, count=1)
    found, unknown = [], []
    for item in items(text)[:MAX_ITEMS]:
        number, unit, rest = amount(item)
        food, _ = match(WORD.findall(rest))
        if not food:
            unknown.append(item)
            continue
        grams, said = grams_for(number, unit, food)
        if food['name'] in DRY and grams <= DRY_UP_TO and (unit is None or unit_grams(unit, food) == 1):
            food = FOOD_BY_NAME[DRY[food['name']]]  # «овсянка 60 г» is weighed dry
        if grams > MAX_GRAMS:
            grams, said = MAX_GRAMS, f'{MAX_GRAMS / 1000:g} кг — больше за раз не считаю'
        k = grams / 100
        found.append(dict(name=food['name'], amount=said, grams=round(grams),
                          calories=round(food['kcal'] * k), protein=round(food['protein'] * k, 1),
                          fat=round(food['fat'] * k, 1), carbs=round(food['carbs'] * k, 1)))
    total = {key: round(sum(f[key] for f in found), 1) for key in ('calories', 'protein', 'fat', 'carbs')}
    total['calories'] = round(total['calories'])
    return dict(items=found, unknown=unknown, total=total)


def title(result, limit=150):
    """A short meal name for the diary: «Гречка варёная 200 г, Яйцо куриное 2 шт»."""
    name = ', '.join(f'{f["name"]} {f["amount"]}' for f in result['items'])
    return name if len(name) <= limit else name[:limit - 1] + '…'


def describe(result):
    """The breakdown as chat text."""
    lines = [f'• {f["name"]} — {f["amount"]}: {f["calories"]} ккал · Б {f["protein"]:g} · Ж {f["fat"]:g} · У {f["carbs"]:g}'
             for f in result['items']]
    if result['unknown']:
        lines.append('Не нашёл в таблице: ' + ', '.join(f'«{u}»' for u in result['unknown'][:5])
                     + '. Уточните название или впишите калории вручную.')
    t = result['total']
    lines.append(f'\nИтого: {t["calories"]} ккал · Б {t["protein"]:g} · Ж {t["fat"]:g} · У {t["carbs"]:g} г')
    return '\n'.join(lines)
