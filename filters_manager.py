import re
from datetime import datetime
from database import UserFilter
from zakupki_parser import Purchase

# 100% точные географические названия (БЕЗ цифр и двусмысленных слов)
STRICT_REGION_DICTIONARY = {
    "хабаровский край": [
        "хабаровск", "комсомольск-на-амуре", "комсомольск", "амурск", "вяземск",
        "бикин", "советская гавань", "совгаван", "ванино", "чегдомын",
        "николаевск-на-амуре", "солнечный район", "хабаровского края", "хабаровский край"
    ],
    "хабаровск": ["хабаровск", "хабаровского края", "хабаровский край"],

    "приморский край": [
        "владивосток", "уссурийск", "находка", "находке", "находки", "артём", "артем",
        "арсеньев", "партизанск", "спасск-дальний", "спасск", "большой камень",
        "фокино", "дальнегорск", "лесозаводск", "дальнереченск", "приморского края",
        "приморский край", "приморье"
    ],
    "приморье": ["владивосток", "уссурийск", "находк", "артем", "приморск"],
    "владивосток": ["владивосток", "приморского края", "приморский край"],

    "еао": [
        "биробиджан", "еврейская автономная", "еврейской автономной", "облучье",
        "облученск", "смидович", "ленинское", "амурзет", "еао"
    ],
    "еврейская автономная область": ["биробиджан", "еврейск", "еао", "облучье"],
    "биробиджан": ["биробиджан", "еврейск", "еао"],

    "сахалинская область": [
        "южно-сахалинск", "сахалин", "сахалинск", "холмск", "корсаков", "оха",
        "невельск", "поронайск", "курильск", "южно-курильск", "углегорск",
        "долинск", "александровск-сахалинск", "ноглики", "тымовское", "сахалинской области"
    ],
    "сахалин": ["южно-сахалинск", "сахалин", "холмск", "корсаков", "оха"],
    "южно-сахалинск": ["южно-сахалинск", "сахалин"],
}


def get_word_stem(word: str) -> str:
    """Отрезает окончания слов для умного поиска по корню"""
    w = re.sub(r'[^а-яёa-z0-9]', '', word.lower())
    if len(w) <= 3:
        return w
    endings = [
        'овский', 'евский', 'инский', 'иями', 'ями', 'ами', 'ов', 'ев', 'ей',
        'иях', 'ях', 'ах', 'ого', 'его', 'ому', 'ему', 'ыми', 'ими', 'ых', 'их',
        'ое', 'ее', 'ие', 'ые', 'ая', 'яя', 'ою', 'ею', 'ую', 'юю', 'ый', 'ий',
        'ой', 'ей', 'ам', 'ям', 'ом', 'ем', 'е', 'и', 'ы', 'а', 'я', 'у', 'ю', 'о'
    ]
    for end in endings:
        if w.endswith(end) and (len(w) - len(end)) >= 3:
            return w[:-len(end)]
    return w


def matches_filter(purchase: Purchase, user_filter: UserFilter) -> bool:
    """Проверяет закупку по критериям фильтра"""
    now = datetime.now()

    # 1. Проверка срока окончания подачи (только актуальные)
    if purchase.end_date and purchase.end_date < now.replace(hour=0, minute=0, second=0):
        return False

    full_text = f"{purchase.title} {purchase.description} {purchase.customer} {purchase.region}".lower()

    # 2. ЖЕСТКАЯ ГЕО-ПРОВЕРКА (Убирает Читу, Москву и любые посторонние города)
    if user_filter.regions:
        requested_regions = [r.strip().lower() for r in user_filter.regions.split(",") if r.strip()]
        if requested_regions:
            region_found = False
            for req in requested_regions:
                # Находим маркеры городов для этого региона
                markers = []
                for k, v in STRICT_REGION_DICTIONARY.items():
                    if k in req or req in k:
                        markers.extend(v)

                if not markers:
                    markers = [req]

                # Проверяем вхождение хотя бы одного города/района в текст закупки
                if any(m in full_text for m in markers):
                    region_found = True
                    break

            # Если городов целевого региона в закупке нет — отклоняем
            if not region_found:
                return False

    # 3. Проверка цены
    if user_filter.min_price is not None and purchase.price > 0:
        if purchase.price < user_filter.min_price:
            return False

    if user_filter.max_price is not None and purchase.price > 0:
        if purchase.price > user_filter.max_price:
            return False

    # 4. Проверка закона
    if user_filter.law_type:
        if user_filter.law_type == "44" and "44" not in purchase.law_type:
            return False
        if user_filter.law_type == "223" and "223" not in purchase.law_type:
            return False

    # 5. Проверка по ключевым словам (гибкий поиск по корням)
    if user_filter.keywords:
        raw_keywords = [kw.strip().lower() for kw in user_filter.keywords.split(",") if kw.strip()]
        if raw_keywords:
            matched = False
            for kw in raw_keywords:
                words = kw.split()
                stems = [get_word_stem(w) for w in words if len(w) > 2]
                if stems and all(stem in full_text for stem in stems):
                    matched = True
                    break
            if not matched:
                return False

    # 6. Исключения
    if user_filter.exclude_keywords:
        exclude_raw = [kw.strip().lower() for kw in user_filter.exclude_keywords.split(",") if kw.strip()]
        for ex in exclude_raw:
            stems = [get_word_stem(w) for w in ex.split() if len(w) > 2]
            if stems and all(stem in full_text for stem in stems):
                return False

    return True


def format_purchase(purchase: Purchase) -> str:
    price_str = f"{purchase.price:,.2f} ₽".replace(",", " ") if purchase.price > 0 else "Не указана"

    end_date_str = ""
    if purchase.end_date:
        end_date_str = purchase.end_date.strftime("%d.%m.%Y")

    text = (
        f"🔔 <b>Актуальная закупка</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 <b>Номер:</b> <code>{purchase.number}</code>\n"
        f"📝 <b>Объект:</b> {purchase.title[:350]}\n"
    )

    if purchase.customer:
        text += f"🏢 <b>Заказчик:</b> {purchase.customer[:250]}\n"

    text += f"💰 <b>Цена:</b> {price_str}\n"

    if purchase.law_type:
        text += f"📜 <b>Закон:</b> {purchase.law_type}\n"

    if end_date_str:
        text += f"⏰ <b>Подача заявок до:</b> <b>{end_date_str}</b>\n"

    text += f"━━━━━━━━━━━━━━━"
    return text


def format_filter_info(f: UserFilter) -> str:
    text = f"📌 <b>Фильтр #{f.id}: {f.name}</b>\n"

    if f.keywords:
        kw_preview = f.keywords[:80] + "..." if len(f.keywords) > 80 else f.keywords
        text += f"🔍 Ключевые слова: {kw_preview}\n"
    if f.min_price is not None:
        text += f"💰 Мин. цена: {f.min_price:,.0f} ₽\n"
    if f.max_price is not None:
        text += f"💰 Макс. цена: {f.max_price:,.0f} ₽\n"
    if f.regions:
        text += f"📍 Регионы: {f.regions}\n"
    if f.law_type:
        text += f"📜 Закон: {f.law_type}-ФЗ\n"

    status = "✅ Активен" if f.is_active else "⏸ Приостановлен"
    text += f"Статус: {status}\n"

    return text