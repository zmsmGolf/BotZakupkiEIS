import asyncio
import logging
import sys
import socket
import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from config import BOT_TOKEN
from database import (
    init_db, get_or_create_user, add_filter, get_user_filters,
    delete_filter, add_favorite, remove_favorite, get_favorites,
    cache_purchase,
)
from filters_manager import format_filter_info, format_purchase
from scheduler import PurchaseChecker, get_purchase_markup
from zakupki_parser import ZakupkiParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# === Настройки зеркала для стабильной работы в РФ ===
# Используем проверенное зеркало, если прямой доступ к api.telegram.org тормозит
CUSTOM_API = TelegramAPIServer.from_base('https://api.telegram-proxy.org')

class AddFilterStates(StatesGroup):
    name, keywords, exclude_keywords, min_price, max_price, regions, law_type, okpd2, confirm = [State() for _ in range(9)]

class QuickSearchStates(StatesGroup):
    query = State()

router = Router()

def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Мои фильтры"), KeyboardButton(text="➕ Добавить фильтр")],
        [KeyboardButton(text="🔄 Проверить сейчас"), KeyboardButton(text="🔎 Быстрый поиск")],
        [KeyboardButton(text="⭐️ Избранное"), KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="⚙️ Настройки")]
    ], resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

@router.message(F.text == "❌ Отмена")
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено. Главное меню:", reply_markup=main_keyboard())

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer(f"👋 Бот запущен в Москве и готов к поиску!", reply_markup=main_keyboard())

# --- Обработчики (оставляем логику как была) ---

@router.message(F.text == "⭐️ Избранное")
async def show_favorites_handler(message: Message):
    favs = await get_favorites(message.from_user.id)
    if not favs:
        await message.answer("⭐️ Избранное пусто.", reply_markup=main_keyboard())
        return
    for f in favs:
        btn = [[InlineKeyboardButton(text="🔗 Сайт", url=f.url), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fav_rem_{f.purchase_number}")]]
        await message.answer(f"📋 №{f.purchase_number}\n📝 {f.title[:200]}...", reply_markup=InlineKeyboardMarkup(inline_keyboard=btn))

@router.callback_query(F.data.startswith("fav_add_"))
async def add_to_fav(call: CallbackQuery):
    num = call.data.replace("fav_add_", "")
    if await add_favorite(call.from_user.id, num):
        await call.answer("⭐ Добавлено!")
    else: await call.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("fav_rem_"))
async def rem_from_fav(call: CallbackQuery):
    num = call.data.replace("fav_rem_", "")
    await remove_favorite(call.from_user.id, num)
    await call.answer("🗑 Удалено")

# --- Повторите вашу логику FSM для AddFilter и Search (как в прошлых версиях) ---

async def set_bot_commands(bot: Bot):
    commands = [BotCommand(command="start", description="Меню"), BotCommand(command="check", description="Поиск")]
    try:
        await bot.set_my_commands(commands)
    except:
        pass # Игнорируем ошибку, если API тормозит

async def main():
    print("!!! ЗАПУСК ЧЕРЕЗ ЗЕРКАЛО В МОСКВЕ !!!")
    await init_db()
    
    # Тонкая настройка IPv4 + Зеркало API
    connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)
    session = AiohttpSession(api=CUSTOM_API, connector=connector)
    
    bot = Bot(token=BOT_TOKEN, session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    checker = PurchaseChecker(bot)
    bot.__dict__["purchase_checker"] = checker
    await checker.start()
    
    print("🚀 БОТ ПОДКЛЮЧЕН К ЗЕРКАЛУ!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
