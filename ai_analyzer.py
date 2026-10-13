import os
import aiohttp
import logging
from dotenv import load_dotenv

# Принудительная загрузка переменных окружения
load_dotenv()

logger = logging.getLogger(__name__)

CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"


async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ закупки через Google Gemini"""
    
    # Считываем ключ динамически прямо в момент запроса
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    
    if not api_key or "AIza" not in api_key:
        return (
            "⚠️ <b>Ключ Gemini API не настроен в Bothost.ru!</b>\n\n"
            "Добавьте переменную <code>GEMINI_API_KEY</code> со значением вашего ключа в панели хостинга."
        )

    # Динамическое формирование URL
    gemini_url = f"{CF_PROXY_URL}/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

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
        f"2. 📦 Ключевые потребности и товары\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски (документы, лицензии, штрафы)\n"
        f"Отвечай на русском языке, коротко, с эмодзи."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(gemini_url, json=payload, headers=headers, timeout=25) as resp:
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
