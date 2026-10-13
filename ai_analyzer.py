import os
import aiohttp
import logging
import html

logger = logging.getLogger(__name__)

# Используем бесплатный ключ Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный анализ закупки через Google Gemini"""
    
    if not GEMINI_API_KEY:
        return "⚠️ Ключ GEMINI_API_KEY не найден в настройках хостинга."

    price_str = f"{price:,.2f} ₽".replace(",", " ") if price > 0 else "Не указана"

    # Промпт (задание) для нейросети
    prompt = (
        f"Ты эксперт по тендерам РФ. Проанализируй закупку:\n"
        f"Лот: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши кратко:\n"
        f"1. 📋 Суть (что купить/сделать)\n"
        f"2. 📦 Основные позиции\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски\n"
        f"Отвечай на русском языке, используй списки и эмодзи."
    )

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 800,
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GEMINI_URL, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Извлекаем ответ из структуры Google Gemini
                    return data['candidates'][0]['content']['parts'][0]['text']
                else:
                    logger.error(f"Gemini Error: {resp.status}")
                    return "❌ Не удалось получить бесплатный анализ (ошибка API)."
    except Exception as e:
        logger.error(f"Gemini Exception: {e}")
        return "❌ Ошибка связи с ИИ-сервисом."
