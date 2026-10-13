import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Ссылка на ваш Cloudflare воркер
CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"
# Путь к ИИ через воркер
AI_URL = f"{CF_PROXY_URL}/api/v1/chat/completions"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ через OpenRouter и Cloudflare мост"""
    
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not api_key:
        return "⚠️ ОШИБКА: Ключ OPENROUTER_API_KEY не найден в Bothost.ru."

    prompt = (
        f"Ты эксперт по тендерам РФ. Проанализируй закупку:\n"
        f"Объект: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price:,.2f} руб.\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши кратко по пунктам:\n"
        f"1. 📋 Суть (что нужно сделать)\n"
        f"2. 📦 Ключевые требования\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски\n"
        f"Отвечай на русском языке с эмодзи."
    )

    payload = {
        "model": "google/gemini-2.0-flash-exp:free",
        "messages": [{"role": "user", "content": prompt}]
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_URL, json=payload, headers=headers, timeout=40) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    err_msg = await resp.text()
                    logger.error(f"AI Bridge Error {resp.status}: {err_msg}")
                    return f"❌ Ошибка ИИ через мост (Код {resp.status}). Проверьте ключ."
    except Exception as e:
        logger.error(f"AI Connection Error: {e}")
        return "❌ Ошибка связи с ИИ. Попробуйте еще раз."
