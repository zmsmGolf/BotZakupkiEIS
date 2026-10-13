import asyncio
import logging
import sys
import os
import socket
import html
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
    cache_purchase, get_cached_purchase_by_number,
)
from filters_manager import format_filter_info, format_purchase
from scheduler import PurchaseChecker, get_purchase_markup
from zakupki_parser import ZakupkiParser
from ai_analyzer import analyze_purchase_with_ai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


CF_WORKER_URL = "https://my-tg-proxy.zretsky.workers.dev"
CUSTOM_TG_API = TelegramAPIServer.from_base(CF_WORKER_URL)


class IPv4AiohttpSession(AiohttpSession):
    def __init__(self, timeout: float = 35.0):
        super().__init__(api=CUSTOM_TG_API, timeout=timeout)

    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)
            self._session = aiohttp.ClientSession(
                connector=connector,
                json_serialize=self.json_dumps,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session


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
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)


def skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить этот шаг", callback_data="skip")]]
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


@router.message(F.text == "❌ Отмена")
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено. Возвращаюсь в главное меню.", reply_markup=main_keyboard())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await get_or_create_user(message.from_user.id, message.from_user.username)
    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я бот для мониторинга закупок на <b>zakupki.gov.ru</b>\n\n"
        f"📌 Все действия доступны по кнопкам ниже!"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>Справка по боту</b>\n\n"
        "🧠 <b>ИИ-Анализ ТЗ:</b>\n"
        "Нажмите кнопку «🧠 ИИ-Анализ ТЗ» под любой закупкой, и нейросеть подготовит выжимку по рискам, требованиям и условиям за 3 секунды!"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


# === ОБРАБОТЧИК ИИ-АНАЛИЗА ===

@router.callback_query(F.data.startswith("ai_analyze_"))
async def process_ai_analyze(callback: CallbackQuery):
    purchase_number = callback.data.replace("ai_analyze_", "")
    
    await callback.answer("🧠 ИИ анализирует ТЗ... Подождите 3-5 секунд.", show_alert=False)
    
    status_msg = await callback.message.reply("⏳ <b>ИИ сканирует документы и условия закупки...</b>", parse_mode=ParseMode.HTML)
    
    cached = await get_cached_purchase_by_number(purchase_number)
    if cached:
        title = cached.title or "Без названия"
        customer = cached.customer or ""
        price = cached.price or 0.0
        law = cached.law_type or ""
        region = cached.region or ""
    else:
        title = f"Закупка №{purchase_number}"
        customer, price, law, region = "", 0.0, "", ""

    ai_result = await analyze_purchase_with_ai(title=title, customer=customer, price=price, law_type=law, region=region)
    
    out_text = f"🧠 <b>ИИ-АНАЛИЗ ЗАКУПКИ №<code>{purchase_number}</code></b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n{ai_result}"
    
    await status_msg.edit_text(out_text, parse_mode=ParseMode.HTML)


# === Избранное ===

@router.callback_query(F.data.startswith("fav_add_"))
async def process_fav_add(callback: CallbackQuery):
    purchase_number = callback.data.replace("fav_add_", "")
    success = await add_favorite(callback.from_user.id, purchase_number)
    if success:
        await callback.answer("⭐ Закупка добавлена в избранное!")
        fav_text = "❤️ В избранном"
        fav_callback = f"fav_rem_{purchase_number}"
        original_markup = callback.message.reply_markup
        new_inline_keyboard = []
        for row in original_markup.inline_keyboard:
            new_row = []
            for btn in row:
                if btn.callback_data == callback.data:
                    new_row.append(InlineKeyboardButton(text=fav_text, callback_data=fav_callback))
                else:
                    new_row.append(btn)
            new_inline_keyboard.append(new_row)
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_inline_keyboard))
    else:
        await callback.answer("❌ Ошибка добавления", show_alert=True)


@router.callback_query(F.data.startswith("fav_rem_"))
async def process_fav_rem(callback: CallbackQuery):
    purchase_number = callback.data.replace("fav_rem_", "")
    await remove_favorite(callback.from_user.id, purchase_number)
    await callback.answer("🗑 Удалено из избранного")
    fav_text = "⭐️ В избранное"
    fav_callback = f"fav_add_{purchase_number}"
    original_markup = callback.message.reply_markup
    new_inline_keyboard = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if btn.callback_data == callback.data:
                new_row.append(InlineKeyboardButton(text=fav_text, callback_data=fav_callback))
            else:
                new_row.append(btn)
        new_inline_keyboard.append(new_row)
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_inline_keyboard))


@router.message(Command("favorites"))
@router.message(F.text == "⭐️ Избранное")
async def show_favorites(message: Message):
    favs = await get_favorites(message.from_user.id)
    if not favs:
        await message.answer("⭐️ Ваш список избранного пуст.", parse_mode=ParseMode.HTML, reply_markup=main_keyboard())
        return
    await message.answer(f"⭐️ <b>Ваши избранные закупки ({len(favs)}):</b>", parse_mode=ParseMode.HTML)
    for f in favs:
        price_str = f"{f.price:,.2f} ₽".replace(",", " ") if f.price else "Не указана"
        text = f"📋 <b>Номер:</b> <code>{f.purchase_number}</code>\n📝 <b>Название:</b> {html.escape(f.title[:200])}...\n💰 <b>Цена:</b> {price_str}\n"
        buttons = []
        if f.url:
            buttons.append(InlineKeyboardButton(text="🔗 Сайт", url=f.url))
        buttons.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fav_rem_{f.purchase_number}"))
        markup = InlineKeyboardMarkup(inline_keyboard=[buttons, [InlineKeyboardButton(text="🧠 ИИ-Анализ ТЗ", callback_data=f"ai_analyze_{f.purchase_number}")]])
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await asyncio.sleep(0.2)


# === Создание фильтра (FSM) ===

@router.message(Command("add_filter"))
@router.message(F.text == "➕ Добавить фильтр")
async def start_add_filter(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddFilterStates.name)
    await message.answer("📌 Шаг 1/8: Введите <b>название</b> фильтра", parse_mode=ParseMode.HTML, reply_markup=cancel_keyboard())


@router.message(AddFilterStates.name)
async def process_filter_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddFilterStates.keywords)
    await message.answer("🔍 Шаг 2/8: Введите <b>ключевые слова</b> через запятую:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())


@router.callback_query(F.data == "skip", AddFilterStates.keywords)
async def skip_keywords(callback: CallbackQuery, state: FSMContext):
    await state.update_data(keywords=None)
    await state.set_state(AddFilterStates.exclude_keywords)
    await callback.message.edit_text("🚫 Шаг 3/8: Введите <b>исключающие слова</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())
    await callback.answer()


@router.message(AddFilterStates.keywords)
async def process_keywords(message: Message, state: FSMContext):
    await state.update_data(keywords=message.text.strip())
    await state.set_state(AddFilterStates.exclude_keywords)
    await message.answer("🚫 Шаг 3/8: Введите <b>исключающие слова</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())


@router.callback_query(F.data == "skip", AddFilterStates.exclude_keywords)
async def skip_exclude(callback: CallbackQuery, state: FSMContext):
    await state.update_data(exclude_keywords=None)
    await state.set_state(AddFilterStates.min_price)
    await callback.message.edit_text("💰 Шаг 4/8: Введите <b>минимальную цену</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())
    await callback.answer()


@router.message(AddFilterStates.exclude_keywords)
async def process_exclude(message: Message, state: FSMContext):
    await state.update_data(exclude_keywords=message.text.strip())
    await state.set_state(AddFilterStates.min_price)
    await message.answer("💰 Шаг 4/8: Введите <b>минимальную цену</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())


@router.callback_query(F.data == "skip", AddFilterStates.min_price)
async def skip_min_price(callback: CallbackQuery, state: FSMContext):
    await state.update_data(min_price=None)
    await state.set_state(AddFilterStates.max_price)
    await callback.message.edit_text("💰 Шаг 5/8: Введите <b>максимальную цену</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())
    await callback.answer()


@router.message(AddFilterStates.min_price)
async def process_min_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(" ", "").replace(",", "."))
        await state.update_data(min_price=price)
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    await state.set_state(AddFilterStates.max_price)
    await message.answer("💰 Шаг 5/8: Введите <b>максимальную цену</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())


@router.callback_query(F.data == "skip", AddFilterStates.max_price)
async def skip_max_price(callback: CallbackQuery, state: FSMContext):
    await state.update_data(max_price=None)
    await state.set_state(AddFilterStates.regions)
    await callback.message.edit_text("📍 Шаг 6/8: Введите <b>регион(ы)</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())
    await callback.answer()


@router.message(AddFilterStates.max_price)
async def process_max_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(" ", "").replace(",", "."))
        await state.update_data(max_price=price)
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    await state.set_state(AddFilterStates.regions)
    await message.answer("📍 Шаг 6/8: Введите <b>регион(ы)</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())


@router.callback_query(F.data == "skip", AddFilterStates.regions)
async def skip_regions(callback: CallbackQuery, state: FSMContext):
    await state.update_data(regions=None)
    await state.set_state(AddFilterStates.law_type)
    await callback.message.edit_text("📜 Шаг 7/8: Выберите <b>тип закона</b>", parse_mode=ParseMode.HTML, reply_markup=law_type_keyboard())
    await callback.answer()


@router.message(AddFilterStates.regions)
async def process_regions(message: Message, state: FSMContext):
    await state.update_data(regions=message.text.strip())
    await state.set_state(AddFilterStates.law_type)
    await message.answer("📜 Шаг 7/8: Выберите <b>тип закона</b>", parse_mode=ParseMode.HTML, reply_markup=law_type_keyboard())


@router.callback_query(F.data.startswith("law_"), AddFilterStates.law_type)
async def process_law_type(callback: CallbackQuery, state: FSMContext):
    law = callback.data.replace("law_", "")
    if law == "all": law = None
    await state.update_data(law_type=law)
    await state.set_state(AddFilterStates.okpd2)
    await callback.message.edit_text("📊 Шаг 8/8: Введите <b>коды ОКПД2</b>:", parse_mode=ParseMode.HTML, reply_markup=skip_keyboard())
    await callback.answer()


@router.callback_query(F.data == "skip", AddFilterStates.okpd2)
async def skip_okpd2(callback: CallbackQuery, state: FSMContext):
    await state.update_data(okpd2_codes=None)
    await show_filter_summary(callback.message, state)
    await callback.answer()


@router.message(AddFilterStates.okpd2)
async def process_okpd2(message: Message, state: FSMContext):
    await state.update_data(okpd2_codes=message.text.strip())
    await show_filter_summary(message, state)


async def show_filter_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(AddFilterStates.confirm)
    summary = f"📋 <b>Проверьте ваш фильтр: «{html.escape(str(data.get('name', '-')))}»</b>\n\nСохраняем?"
    await message.answer(summary, parse_mode=ParseMode.HTML, reply_markup=confirm_keyboard())


@router.callback_query(F.data == "confirm_save", AddFilterStates.confirm)
async def save_filter(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await add_filter(callback.from_user.id, data)
    await state.clear()
    await callback.message.edit_text("✅ Фильтр сохранен!", parse_mode=ParseMode.HTML)
    await callback.message.answer("Выберите действие:", reply_markup=main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel", AddFilterStates.confirm)
async def cancel_filter(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание фильтра отменено.")
    await callback.message.answer("Выберите действие:", reply_markup=main_keyboard())
    await callback.answer()


@router.message(Command("my_filters"))
@router.message(F.text == "🔍 Мои фильтры")
async def show_filters(message: Message):
    filters = await get_user_filters(message.from_user.id)
    if not filters:
        await message.answer("📭 У вас пока нет созданных фильтров.", reply_markup=main_keyboard())
        return
    await message.answer(f"📋 <b>Ваши фильтры ({len(filters)}):</b>", parse_mode=ParseMode.HTML)
    for f in filters:
        await message.answer(format_filter_info(f), parse_mode=ParseMode.HTML, reply_markup=filter_actions_keyboard(f.id))


@router.callback_query(F.data.startswith("delete_filter_"))
async def process_delete_filter(callback: CallbackQuery):
    filter_id = int(callback.data.replace("delete_filter_", ""))
    if await delete_filter(filter_id, callback.from_user.id):
        await callback.message.edit_text("🗑 Фильтр удален!")
    else:
        await callback.message.edit_text("❌ Ошибка удаления.")
    await callback.answer()


@router.message(Command("check"))
@router.message(F.text == "🔄 Проверить сейчас")
async def manual_check(message: Message):
    status_msg = await message.answer("🔄 Запущен сканер... Подождите ⏳")
    checker: PurchaseChecker = message.bot.__dict__.get("purchase_checker")
    if checker:
        count = await checker.manual_check(message.from_user.id)
        await status_msg.edit_text(f"✅ Проверка завершена! Найдено лотов: <b>{count}</b>", parse_mode=ParseMode.HTML)


@router.message(Command("search"))
@router.message(F.text == "🔎 Быстрый поиск")
async def start_quick_search(message: Message, state: FSMContext):
    await state.set_state(QuickSearchStates.query)
    await message.answer("🔎 Введите ключевое слово:", reply_markup=cancel_keyboard())


@router.message(QuickSearchStates.query)
async def process_quick_search(message: Message, state: FSMContext):
    query = message.text.strip()
    await state.clear()
    status_msg = await message.answer(f"🔍 Ищу «{html.escape(query)}»...", reply_markup=main_keyboard())
    parser = ZakupkiParser()
    try:
        purchases = await parser.search_purchases(keywords=query, days_back=30)
        if not purchases:
            await status_msg.edit_text("😔 Ничего не найдено.")
        else:
            await status_msg.edit_text(f"✅ Найдено закупок: <b>{len(purchases)}</b>", parse_mode=ParseMode.HTML)
            for purchase in purchases[:5]:
                await cache_purchase(purchase)
                markup = await get_purchase_markup(message.from_user.id, purchase)
                await message.answer(format_purchase(purchase), parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)
                await asyncio.sleep(0.3)
    finally:
        await parser.close()


@router.message(F.text == "⚙️ Настройки")
async def settings(message: Message):
    filters = await get_user_filters(message.from_user.id)
    await message.answer(f"⚙️ <b>Настройки</b>\n\n📊 Ваши фильтры: {len(filters)}\n🧠 ИИ-Аналитик: ✅ Подключен (DeepSeek)", parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


@router.error()
async def global_error_handler(event, exception):
    logger.error(f"Ошибка в обработчике: {exception}", exc_info=True)
    return True


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="my_filters", description="Мои фильтры"),
        BotCommand(command="favorites", description="Избранное"),
        BotCommand(command="check", description="Проверить закупки"),
        BotCommand(command="help", description="Справка и помощь"),
    ]
    await bot.set_my_commands(commands)


async def main():
    print("!!! ЗАПУСК БОТА С ИИ-АНАЛИТИКОМ !!!")
    await init_db()

    if not BOT_TOKEN or "ВАШ_ТОКЕН" in BOT_TOKEN:
        print("❌ ОШИБКА: Токен не найден!")
        return

    session = IPv4AiohttpSession(timeout=35.0)
    bot = Bot(token=BOT_TOKEN, session=session)

    try:
        try: await set_bot_commands(bot)
        except Exception as e: logger.warning(f"Пропущена установка меню: {e}")

        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        dp.include_router(router)

        checker = PurchaseChecker(bot)
        bot.__dict__["purchase_checker"] = checker
        await checker.start()

        print("🚀🚀🚀 БОТ С ИИ-АНАЛИТИКОМ УСПЕШНО ЗАПУЩЕН! 🚀🚀🚀")

        try: await bot.delete_webhook(drop_pending_updates=True)
        except Exception: pass

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    finally:
        if "purchase_checker" in bot.__dict__:
            try: await bot.__dict__["purchase_checker"].stop()
            except Exception: pass
        try: await bot.session.close()
        except Exception: pass


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logger.info("Бот остановлен.")
