import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Ссылка на ваш воркер (без слеша в конце)
CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"
GROQ_URL = f"{CF_PROXY_URL}/openai/v1/chat/completions"

async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ через Groq и Cloudflare"""
    
    # Ключ берется ТОЛЬКО из переменных Bothost.ru
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not api_key or "gsk_" not in api_key:
        return "⚠️ ОШИБКА: НОВЫЙ ключ GROQ_API_KEY не найден в панели Bothost.ru."

    price_str = f"{price:,.2f} ₽".replace(",", " ") if price > 0 else "Не указана"

    prompt = (
        f"Ты эксперт по тендерам РФ. Проанализируй закупку:\n"
        f"Объект: {title}\n"
        f"Заказчик: {customer}\n"
        f"Цена: {price_str}\n"
        f"Закон: {law_type}\n"
        f"Регион: {region}\n\n"
        f"Напиши кратко:\n"
        f"1. 📋 Суть (что сделать)\n"
        f"2. 📦 Основные требования\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски\n"
        f"Отвечай на русском языке, используй эмодзи."
    )

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    err_text = await resp.text()
                    logger.error(f"Groq Error {resp.status}: {err_text}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте НОВЫЙ ключ в Bothost."
    except Exception as e:
        logger.error(f"Groq Connection Error: {e}")
        return "❌ Ошибка связи с ИИ. Попробуйте еще раз."
