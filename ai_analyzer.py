import os
import aiohttp
import logging

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"

# Официальный рабочий эндпоинт Gemini 1.5 Flash
GEMINI_URL = f"{CF_PROXY_URL}/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"


async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ закупки через Google Gemini"""
    
    if not GEMINI_API_KEY or "AIza" not in GEMINI_API_KEY:
        return (
            "⚠️ <b>Ключ Gemini API не настроен!</b>\n\n"
            "Добавьте переменную <code>GEMINI_API_KEY</code> в панели Bothost.ru.\n"
            "Ключ должен начинаться на <code>AIzaSy...</code>"
        )

    price_str = f"{price:,.2f} ₽".replace(",", " ") if price > 0 else "Не указана"

    prompt = (
        f"Ты опытный тендерный специалист РФ. Проанализируй закупку:\n"
        f"Наименование: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Сделай краткую выжимку по пунктам:\n"
        f"1. 📋 Суть закупки (что купить/сделать)\n"
        f"2. 📦 Ключевые требования и товары\n"
        f"3. 💰 Оценка привлекательности\n"
        f"4. ⚠️ Главные риски (документы, лицензии, штрафы)\n"
        f"Отвечай на русском языке, коротко, с эмодзи."
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
                        return "❌ Не удалось прочитать ответ от нейросети."
                else:
                    err_body = await resp.text()
                    logger.error(f"Gemini API Error {resp.status}: {err_body}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте правильность GEMINI_API_KEY."
    except Exception as e:
        logger.error(f"Gemini Connection Exception: {e}")
        return "❌ Не удалось связаться с ИИ-сервисом."
