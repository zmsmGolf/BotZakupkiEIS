import asyncio
import logging
import sys
import os
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


# === Настройка моста Cloudflare ===
CF_WORKER_URL = "https://my-tg-proxy.zretsky.workers.dev"
CUSTOM_TG_API = TelegramAPIServer.from_base(CF_WORKER_URL)


class IPv4AiohttpSession(AiohttpSession):
    """Специальная сессия aiogram для работы в РФ через Cloudflare и IPv4"""
    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)
            self._session = aiohttp.ClientSession(
                connector=connector,
                json_serialize=self.json_dumps,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session


# === Состояния FSM ===

class AddFilterStates(StatesGroup):
    name = State()
    keywords = State()
    exclude_keywords = State()
    min_price = State()
    max_price = State()
    regions = State()
    law_type = State()
    okpd2 = State()
    confirm = State()


class QuickSearchStates(StatesGroup):
    query = State()


router = Router()


# === Клавиатуры ===

def main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="🔍 Мои фильтры"),
            KeyboardButton(text="➕ Добавить фильтр"),
        ],
        [
            KeyboardButton(text="🔄 Проверить сейчас"),
            KeyboardButton(text="🔎 Быстрый поиск"),
        ],
        [
            KeyboardButton(text="⭐️ Избранное"),
            KeyboardButton(text="ℹ️ Помощь"),
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="❌ Отмена")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить этот шаг", callback_data="skip")]
        ]
    )


def law_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="44-ФЗ", callback_data="law_44"),
                InlineKeyboardButton(text="223-ФЗ", callback_data="law_223"),
            ],
            [
                InlineKeyboardButton(text="Все законы (44-ФЗ и 223-ФЗ)", callback_data="law_all"),
            ],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить фильтр", callback_data="confirm_save"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_cancel"),
            ]
        ]
    )


def filter_actions_keyboard(filter_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить этот фильтр",
                    callback_data=f"delete_filter_{filter_id}",
                ),
            ]
        ]
    )


# === Общие команды и отмена ===

@router.message(F.text == "❌ Отмена")
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()

    await message.answer(
        "❌ Действие отменено. Возвращаюсь в главное меню.",
        reply_markup=main_keyboard()
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await get_or_create_user(
        message.from_user.id, message.from_user.username
    )

    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я бот для мониторинга закупок на <b>zakupki.gov.ru</b>\n\n"
        f"🔹 <b>Используйте кнопки внизу для управления:</b>\n"
        f"• <b>➕ Добавить фильтр</b> — подбор закупок по вашим темам\n"
        f"• <b>🔄 Проверить сейчас</b> — мгновенный запуск поиска\n"
        f"• <b>🔎 Быстрый поиск</b> — разгрузка результатов по запросу\n"
        f"• <b>⭐️ Избранное</b> — ваши сохраненные лоты\n\n"
        f"📌 Все действия доступны по кнопкам ниже!"
    )

    await message.answer(
        welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard()
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>Справка по боту</b>\n\n"
        "<b>Кнопки меню:</b>\n"
        "➕ <b>Добавить фильтр</b> — создать новый фильтр\n"
        "🔍 <b>Мои фильтры</b> — ваши активные фильтры\n"
        "🔄 <b>Проверить сейчас</b> — ручной запуск сканера\n"
        "🔎 <b>Быстрый поиск</b> — мгновенный поиск лотов\n"
        "⭐️ <b>Избранное</b> — ваши закладки\n\n"
        "Жмите «⭐️ В избранное» под закупкой, чтобы сохранить её!"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


# === Избранное ===

@router.callback_query(F.data.startswith("fav_add_"))
async def process_fav_add(callback: CallbackQuery):
    purchase_number = callback.data.replace("fav_add_", "")
    success = await add_favorite(callback.from_user.id, purchase_number)
    if success:
        await callback.answer("⭐ Добавлено в избранное!")
        # Логика обновления кнопок в сообщении...
    else:
        await callback.answer("❌ Ошибка добавления")

@router.callback_query(F.data.startswith("fav_rem_"))
async def process_fav_rem(callback: CallbackQuery):
    purchase_number = callback.data.replace("fav_rem_", "")
    await remove_favorite(callback.from_user.id, purchase_number)
    await callback.answer("🗑 Удалено")

@router.message(Command("favorites"))
@router.message(F.text == "⭐️ Избранное")
async def show_favorites(message: Message):
    favs = await get_favorites(message.from_user.id)
    if not favs:
        await message.answer("⭐️ Избранное пусто.", reply_markup=main_keyboard())
        return
    for f in favs:
        price_str = f"{f.price:,.2f} ₽".replace(",", " ") if f.price else "Не указана"
        btn = [[InlineKeyboardButton(text="🔗 Сайт", url=f.url), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fav_rem_{f.purchase_number}")]]
        await message.answer(f"📋 №{f.purchase_number}\n📝 {f.title[:200]}...\n💰 Цена: {price_str}", reply_markup=InlineKeyboardMarkup(inline_keyboard=btn))


# === Создание фильтра (FSM) ===

@router.message(Command("add_filter"))
@router.message(F.text == "➕ Добавить фильтр")
async def start_add_filter(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddFilterStates.name)
    await message.answer("Введите название фильтра:", reply_markup=cancel_keyboard())

@router.message(AddFilterStates.name)
async def process_filter_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddFilterStates.keywords)
    await message.answer("Введите ключевые слова через запятую:", reply_markup=skip_keyboard())

# [Здесь сокращена часть логики FSM шагов для краткости, она должна оставаться как в предыдущих версиях]
# Важно: Обработчики AddFilterStates.keywords, exclude, price, regions и т.д. должны быть в полном коде.

@router.callback_query(F.data == "confirm_save", AddFilterStates.confirm)
async def save_filter_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await add_filter(callback.from_user.id, data)
    await state.clear()
    await callback.message.edit_text("✅ Фильтр успешно сохранен!")
    await callback.message.answer("Выберите действие:", reply_markup=main_keyboard())

# === Ручная проверка ===

@router.message(F.text == "🔄 Проверить сейчас")
async def manual_check(message: Message):
    status_msg = await message.answer("🔄 Запущен сканер (50 страниц)... Пожалуйста, ждите.")
    checker: PurchaseChecker = message.bot.__dict__.get("purchase_checker")
    if checker:
        count = await checker.manual_check(message.from_user.id)
        await status_msg.edit_text(f"✅ Проверка завершена! Найдено новых лотов: {count}")
    else:
        await status_msg.edit_text("❌ Ошибка сервиса")

# === Регистрация меню в Telegram ===

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="favorites", description="Избранное"),
        BotCommand(command="check", description="Запустить поиск"),
    ]
    await bot.set_my_commands(commands)


# === Main ===

async def main():
    print("!!! ЗАПУСК БОТА В МОСКВЕ (FIXED) !!!")
    await init_db()

    # ПРАВИЛЬНО: Передаем CUSTOM_TG_API (наш мост) в session, а не в Bot
    session = IPv4AiohttpSession(api=CUSTOM_TG_API, timeout=45.0)
    bot = Bot(token=BOT_TOKEN, session=session)

    try:
        try:
            await set_bot_commands(bot)
            print("✅ Меню команд Telegram установлено!")
        except Exception as e:
            logger.warning(f"Ошибка установки меню: {e}")

        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        dp.include_router(router)

        checker = PurchaseChecker(bot)
        bot.__dict__["purchase_checker"] = checker
        await checker.start()

        print("🚀🚀🚀 БОТ УСПЕШНО ЗАПУЩЕН! 🚀🚀🚀")
        
        # Безопасный старт без удаления вебхука (чтобы не провоцировать 404 на зеркале)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    finally:
        if "purchase_checker" in bot.__dict__:
            try: await bot.__dict__["purchase_checker"].stop()
            except: pass
        await bot.session.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
