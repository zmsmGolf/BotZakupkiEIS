import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ПРЯМОЙ адрес OpenRouter (работает из РФ без прокси!)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ напрямую через OpenRouter (Mistral / OpenChat)"""
    
    # Получаем ключ из переменных
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    
    if not api_key or len(api_key) < 10:
        return "⚠️ ОШИБКА: Ключ OPENROUTER_API_KEY не найден. Добавьте его в Bothost и нажмите REDEPLOY."

    api_key = api_key.strip()
    price_str = f"{price:,.2f} руб." if price > 0 else "Не указана"

    prompt = (
        f"Ты эксперт по тендерам РФ. Сделай краткий анализ лота:\n"
        f"Объект: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши строго по пунктам:\n"
        f"1. 📋 Суть (что именно нужно сделать/поставить)\n"
        f"2. 📦 Ключевые требования (кратко)\n"
        f"3. 💰 Оценка (выгоден ли лот)\n"
        f"4. ⚠️ Главные риски (документы, сроки, штрафы)\n"
        f"Отвечай на русском языке. Используй эмодзи."
    )

    # Используем модель mistral-7b (самая стабильная бесплатная модель)
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}]
    }

    # ОБЯЗАТЕЛЬНЫЕ заголовки для OpenRouter
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/zmsmGolf/BotZakupkiEIS",
        "X-Title": "ZakupkiMonitorBot",
        "Content-Type": "application/json"
    }

    try:
        # Прямой запрос без использования Cloudflare моста
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    err_text = await resp.text()
                    logger.error(f"OpenRouter Direct Error {resp.status}: {err_text}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте ключ и баланс на OpenRouter."
    except Exception as e:
        logger.error(f"AI Direct Connection Error: {e}")
        return "❌ Не удалось связаться с ИИ. Попробуйте еще раз через минуту."
