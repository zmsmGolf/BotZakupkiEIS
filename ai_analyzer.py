import os
import aiohttp
import logging
from dotenv import load_dotenv

# Загружаем переменные отовсюду
load_dotenv()

logger = logging.getLogger(__name__)

CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ закупки через Google Gemini"""
    
    # Пытаемся найти ключ везде
    api_key = (
        os.environ.get("GEMINI_API_KEY") or 
        os.getenv("GEMINI_API_KEY") or 
        os.getenv("gemini_api_key")
    )
    
    if api_key:
        api_key = api_key.strip()

    if not api_key:
        # Если ключа нет, пишем в логи хостинга список всех доступных переменных для отладки
        logger.error(f"GEMINI_API_KEY NOT FOUND. Available vars: {list(os.environ.keys())}")
        return (
            "⚠️ <b>Ключ Gemini API не виден коду!</b>\n\n"
            "1. Убедитесь, что в Bothost создана переменная <code>GEMINI_API_KEY</code>.\n"
            "2. Нажмите кнопку <b>REDEPLOY (Пересобрать)</b> в панели хостинга."
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
        f"2. 📦 Ключевые требования и товары\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски (документы, штрафы)\n"
        f"Отвечай на русском языке, коротко, с эмодзи."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(gemini_url, json=payload, timeout=25) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    try:
                        return data['candidates'][0]['content']['parts'][0]['text']
                    except:
                        return "❌ Ошибка обработки ответа ИИ."
                else:
                    err_msg = await resp.text()
                    logger.error(f"Gemini API Error {resp.status}: {err_msg}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте ключ."
    except Exception as e:
        logger.error(f"Gemini Exception: {e}")
        return "❌ Ошибка связи с ИИ."
