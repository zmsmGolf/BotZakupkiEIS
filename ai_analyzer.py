import os
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CF_PROXY_URL = "https://my-tg-proxy.zretsky.workers.dev"

# Список доступных бесплатных моделей Google (проверяем по очереди)
MODELS_TO_TRY = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-pro",
    "gemini-1.5-pro"
]


async def analyze_purchase_with_ai(title: str, customer: str = "", price: float = 0.0, law_type: str = "", region: str = "") -> str:
    """Бесплатный ИИ-анализ закупки через Google Gemini с авто-подбором модели"""
    
    api_key = (
        os.environ.get("GEMINI_API_KEY") or 
        os.getenv("GEMINI_API_KEY") or 
        ""
    ).strip()

    if not api_key:
        return (
            "⚠️ <b>Ключ Gemini API не найден!</b>\n\n"
            "Добавьте переменную <code>GEMINI_API_KEY</code> в панели Bothost.ru."
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
        f"2. 📦 Ключевые потребности и товары\n"
        f"3. 💰 Оценка лота\n"
        f"4. ⚠️ Главные риски (документы, лицензии, штрафы)\n"
        f"Отвечай на русском языке, коротко, с эмодзи."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    headers = {"Content-Type": "application/json"}

    # Пробуем доступные модели по очереди
    async with aiohttp.ClientSession() as session:
        for model_name in MODELS_TO_TRY:
            gemini_url = f"{CF_PROXY_URL}/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                async with session.post(gemini_url, json=payload, headers=headers, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        try:
                            return data['candidates'][0]['content']['parts'][0]['text']
                        except (KeyError, IndexError):
                            continue
                    elif resp.status == 404:
                        logger.info(f"Модель {model_name} недоступна (404), пробуем следующую...")
                        continue
                    else:
                        err_text = await resp.text()
                        logger.error(f"Gemini API Error {resp.status} on model {model_name}: {err_text}")
                        return f"❌ Ошибка ИИ (Код {resp.status}). Проверьте API-ключ."
            except Exception as e:
                logger.error(f"Ошибка запроса к {model_name}: {e}")
                continue

    return "❌ Ни одна из бесплатных моделей Google Gemini не ответила. Создайте новый API-ключ в Google AI Studio."
