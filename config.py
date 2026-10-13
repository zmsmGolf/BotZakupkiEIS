import os
from dotenv import load_dotenv

load_dotenv()

# Автоматический выбор токена из всех возможных переменных Bothost
raw_token = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""

# Если случайно загрузился файл .env с заглушкой
if "ВАШ_ТОКЕН" in raw_token or not raw_token:
    BOT_TOKEN = os.getenv("TOKEN") or raw_token
else:
    BOT_TOKEN = raw_token

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 15))

# Сохранение базы данных в защищенную папку Bothost (/app/data)
if os.path.exists("/app/data"):
    DATABASE_URL = "sqlite+aiosqlite:////app/data/zakupki_bot.db"
else:
    DATABASE_URL = "sqlite+aiosqlite:///zakupki_bot.db"

ZAKUPKI_SEARCH_URL = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
ZAKUPKI_API_URL = "https://zakupki.gov.ru/api/search/1.2/search"
ZAKUPKI_CARD_URL = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
