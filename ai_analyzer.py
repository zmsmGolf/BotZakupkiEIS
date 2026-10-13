import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Прямой адрес OpenRouter (работает из РФ без прокси!)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ через OpenRouter (Gemini 2.0 Flash)"""
    
    # Считываем ключ OPENROUTER_API_KEY из Bothost
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not api_key or "sk-or" not in api_key:
        return "⚠️ ОШИБКА: Ключ OPENROUTER_API_KEY не найден в панели Bothost.ru."

    price_str = f"{price:,.2f} руб." if price > 0 else "Не указана"

    prompt = (
        f"Ты ведущий эксперт по тендерам РФ. Сделай краткий анализ лота:\n"
        f"Объект: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши строго по пунктам:\n"
        f"1. 📋 Суть (что именно нужно сделать/поставить)\n"
        f"2. 📦 Основные позиции (кратко)\n"
        f"3. 💰 Оценка лота (насколько выгоден)\n"
        f"4. ⚠️ Главные риски (документы, сроки, штрафы)\n"
        f"Отвечай на русском языке. Используй эмодзи."
    )

    payload = {
        "model": "google/gemini-2.0-flash-exp:free",
        "messages": [{"role": "user", "content": prompt}]
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/zmsmGolf/BotZakupkiEIS", # Для OpenRouter
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    err_text = await resp.text()
                    logger.error(f"OpenRouter Error {resp.status}: {err_text}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте ключ в Bothost."
    except Exception as e:
        logger.error(f"OpenRouter Connection Error: {e}")
        return "❌ Ошибка связи с ИИ. Попробуйте еще раз."
