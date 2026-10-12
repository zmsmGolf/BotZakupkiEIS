import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZAKUPKI_API_KEY = os.getenv("ZAKUPKI_API_KEY", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 30))
DATABASE_URL = "sqlite+aiosqlite:///zakupki_bot.db"

# Базовые URL для API zakupki.gov.ru
ZAKUPKI_SEARCH_URL = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
ZAKUPKI_API_URL = "https://zakupki.gov.ru/api/search/1.2/search"
ZAKUPKI_CARD_URL = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"