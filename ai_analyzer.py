import os
import aiohttp
import logging

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"

# Эндпоинт Gemini API через наш Cloudflare мост
GEMINI_URL = f"{CF_PROXY_URL}/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"


async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный анализ закупки через Google Gemini и Cloudflare"""
    
    if not GEMINI_API_KEY:
        return "⚠️ ОШИБКА: Переменная GEMINI_API_KEY не добавлена в настройки хостинга Bothost.ru."

    price_str = f"{price:,.2f} ₽".replace(",", " ") if price > 0 else "Не указана"

    prompt = (
        f"Ты эксперт по госзакупкам РФ (44-ФЗ и 223-ФЗ). Сделай профессиональный краткий анализ лота:\n"
        f"Наименование: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Структура ответа:\n"
        f"1. 📋 Суть лота (что именно купить/сделать)\n"
        f"2. 📦 Ключевые требования и товары\n"
        f"3. 💰 Оценка привлекательности\n"
        f"4. ⚠️ Риски (лицензии, документы, просрочки)\n"
        f"Отвечай коротко, по делу, с эмодзи на русском языке."
    )

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GEMINI_URL, json=payload, headers=headers, timeout=25) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    try:
                        return data['candidates'][0]['content']['parts'][0]['text']
                    except (KeyError, IndexError):
                        return "❌ Ошибка структуры ответа от ИИ."
                else:
                    err_msg = await resp.text()
                    logger.error(f"Gemini API Error ({resp.status}): {err_msg}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте API-ключ Gemini."
    except Exception as e:
        logger.error(f"Gemini Exception: {e}")
        return "❌ Ошибка соединения с ИИ-сервисом."
