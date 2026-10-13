import os
import aiohttp
import logging

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"

# Эндпоинт для Gemini через ваш Cloudflare
GEMINI_URL = f"{CF_PROXY_URL}/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ закупки через Google Gemini"""
    
    if not GEMINI_API_KEY or "AIza" not in GEMINI_API_KEY:
        return "⚠️ ОШИБКА: GEMINI_API_KEY не настроен в панели Bothost.ru."

    price_str = f"{price:,.2f} ₽".replace(",", " ") if price > 0 else "Не указана"

    prompt = (
        f"Ты эксперт по тендерам РФ. Проанализируй закупку:\n"
        f"Наименование: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши кратко:\n"
        f"1. 📋 Суть (что купить/сделать)\n"
        f"2. 📦 Ключевые потребности\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски\n"
        f"Отвечай на русском языке, используй эмодзи."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GEMINI_URL, json=payload, timeout=25) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    try:
                        return data['candidates'][0]['content']['parts'][0]['text']
                    except (KeyError, IndexError):
                        return "❌ Ошибка структуры ответа от нейросети."
                else:
                    err_msg = await resp.text()
                    logger.error(f"Gemini API Error {resp.status}: {err_msg}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте API-ключ."
    except Exception as e:
        logger.error(f"Gemini Exception: {e}")
        return "❌ Ошибка связи с ИИ-сервисом."
