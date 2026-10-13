import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Ссылка на ваш Cloudflare воркер (БЕЗ слэша в конце)
CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"
AI_URL = f"{CF_PROXY_URL}/api/v1/chat/completions"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """ИИ-анализ через OpenRouter и Cloudflare мост"""
    
    # Пытаемся получить ключ
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    
    if not api_key or len(api_key) < 10:
        return "⚠️ ОШИБКА: Ключ OPENROUTER_API_KEY не виден коду. Проверьте переменные в Bothost и нажмите REDEPLOY."

    api_key = api_key.strip()

    prompt = (
        f"Ты эксперт по тендерам РФ. Сделай краткий анализ лота:\n"
        f"Объект: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price:,.2f} руб.\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши кратко:\n"
        f"1. 📋 Суть\n"
        f"2. 📦 Требования\n"
        f"3. 💰 Привлекательность\n"
        f"4. ⚠️ Риски\n"
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
            async with session.post(AI_URL, json=payload, headers=headers, timeout=45) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    err_msg = await resp.text()
                    logger.error(f"AI Error {resp.status}: {err_msg}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте баланс и ключ на OpenRouter."
    except Exception as e:
        logger.error(f"AI Connection Error: {e}")
        return "❌ Ошибка связи с ИИ через мост. Попробуйте еще раз."
