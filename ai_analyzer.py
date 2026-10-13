import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Официальный прямой эндпоинт Groq AI (OpenAI-совместимый)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Мгновенный бесплатный ИИ-анализ закупки через Groq AI (Llama 3.3 70B / DeepSeek)"""
    
    api_key = (
        os.environ.get("GROQ_API_KEY") or 
        os.getenv("GROQ_API_KEY") or 
        ""
    ).strip()

    if not api_key or "gsk_" not in api_key:
        return (
            "⚠️ <b>Ключ Groq API не настроен!</b>\n\n"
            "Добавьте переменную <code>GROQ_API_KEY</code> со значением ключа (начинается на <code>gsk_...</code>) в панели Bothost.ru."
        )

    price_str = f"{price:,.2f} ₽".replace(",", " ") if price > 0 else "Не указана"

    prompt = (
        f"Ты опытный тендерный специалист и эксперт по госзакупкам РФ (44-ФЗ и 223-ФЗ).\n"
        f"Проанализируй закупку:\n"
        f"• Наименование: {title}\n"
        f"• Заказчик: {customer}\n"
        f"• Цена: {price_str}\n"
        f"• Закон: {law_type}\n"
        f"• Регион: {region}\n\n"
        f"Сделай структурированную, четкую выжимку для поставщика/подрядчика:\n"
        f"1. 📋 Суть закупки (что конкретно требуется купить/сделать простыми словами)\n"
        f"2. 📦 Ключевые позиции и объемы\n"
        f"3. 💰 Оценка привлекательности лота (сложность, маржинальность, аванс)\n"
        f"4. ⚠️ Главные риски (документы, лицензии, сертификаты, жесткие сроки, штрафы)\n\n"
        f"Отвечай коротко, по делу, с эмодзи на русском языке."
    )

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "Ты ведущий эксперт по тендерам РФ."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 900
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_URL, json=payload, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    err_text = await resp.text()
                    logger.error(f"Groq API Error {resp.status}: {err_text}")
                    return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте GROQ_API_KEY."
    except Exception as e:
        logger.error(f"Groq Connection Error: {e}")
        return "❌ Не удалось связаться с ИИ-сервисом."
