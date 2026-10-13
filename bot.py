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

# Настройка моста через Cloudflare
CF_WORKER_URL = "https://my-tg-proxy.zretsky.workers.dev"
from aiogram.client.telegram import TelegramAPIServer
CUSTOM_TG_API = TelegramAPIServer.from_base(CF_WORKER_URL)

# === Оптимизированная сессия IPv4 ===

class IPv4AiohttpSession(AiohttpSession):
    """Специальная сессия aiogram для работы через IPv4"""
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


# === Общие команды ===

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
        "➕ <b>Добавить фильтр</b> — создать новый фильтр с ключевыми словами, ценами и регионами\n"
        "🔍 <b>Мои фильтры</b> — просмотреть и удалить имеющиеся фильтры\n"
        "🔄 <b>Проверить сейчас</b> — запустить мгновенную проверку по вашим фильтрам\n"
        "🔎 <b>Быстрый поиск</b> — найти закупки по любому слову прямо сейчас\n"
        "⭐️ <b>Избранное</b> — список сохраненных вами закупок\n\n"
        "⭐ <b>Избранное:</b>\n"
        "Жмите кнопку «⭐️ В избранное» под любой найденной закупкой, чтобы сохранить её в личный кабинет!"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


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
            
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=new_inline_keyboard)
        )
    else:
        await callback.answer("❌ Не удалось добавить в избранное", show_alert=True)


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
        
    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=new_inline_keyboard)
    )


@router.message(Command("favorites"))
@router.message(F.text == "⭐️ Избранное")
async def show_favorites(message: Message):
    favs = await get_favorites(message.from_user.id)
    
    if not favs:
        await message.answer(
            "⭐️ <b>Ваш список избранного пуст.</b>\n\n"
            "Жмите «⭐️ В избранное» под присланными закупками, чтобы сохранить их сюда.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard()
        )
        return
        
    await message.answer(
        f"⭐️ <b>Ваши избранные закупки ({len(favs)}):</b>",
        parse_mode=ParseMode.HTML
    )
    
    for f in favs:
        price_str = f"{f.price:,.2f} ₽".replace(",", " ") if f.price else "Не указана"
        text = (
            f"📋 <b>Номер:</b> <code>{f.purchase_number}</code>\n"
            f"📝 <b>Название:</b> {f.title[:200]}...\n"
            f"🏢 <b>Заказчик:</b> {f.customer[:150] if f.customer else '-'}\n"
            f"💰 <b>Цена:</b> {price_str}\n"
        )
        
        buttons = []
        if f.url:
            buttons.append(InlineKeyboardButton(text="🔗 Сайт", url=f.url))
        buttons.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fav_rem_{f.purchase_number}"))
        
        markup = InlineKeyboardMarkup(inline_keyboard=[buttons])
        
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        await asyncio.sleep(0.2)


# === Создание фильтра ===

@router.message(Command("add_filter"))
@router.message(F.text == "➕ Добавить фильтр")
async def start_add_filter(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddFilterStates.name)
    await message.answer(
        "📌 <b>Создание нового фильтра</b>\n\n"
        "Шаг 1/8: Введите <b>название</b> фильтра\n"
        "(например: «Поставки ДВ» или «Работы ХК»)",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_keyboard(),
    )


@router.message(AddFilterStates.name)
async def process_filter_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddFilterStates.keywords)
    await message.answer(
        "🔍 Шаг 2/8: Введите <b>ключевые слова</b> для поиска через запятую\n\n"
        "Пример: сантехника, насосы, труба, краска",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )


@router.callback_query(F.data == "skip", AddFilterStates.keywords)
async def skip_keywords(callback: CallbackQuery, state: FSMContext):
    await state.update_data(keywords=None)
    await state.set_state(AddFilterStates.exclude_keywords)
    await callback.message.edit_text(
        "🚫 Шаг 3/8: Введите <b>исключающие слова</b> через запятую\n\n"
        "Пример: ремонт, обслуживание",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )
    await callback.answer()


@router.message(AddFilterStates.keywords)
async def process_keywords(message: Message, state: FSMContext):
    await state.update_data(keywords=message.text.strip())
    await state.set_state(AddFilterStates.exclude_keywords)
    await message.answer(
        "🚫 Шаг 3/8: Введите <b>исключающие слова</b> через запятую\n\n"
        "Пример: ремонт, обслуживание",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )


@router.callback_query(F.data == "skip", AddFilterStates.exclude_keywords)
async def skip_exclude(callback: CallbackQuery, state: FSMContext):
    await state.update_data(exclude_keywords=None)
    await state.set_state(AddFilterStates.min_price)
    await callback.message.edit_text(
        "💰 Шаг 4/8: Введите <b>минимальную цену</b> (в рублях)\n\n"
        "Пример: 50000",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )
    await callback.answer()


@router.message(AddFilterStates.exclude_keywords)
async def process_exclude(message: Message, state: FSMContext):
    await state.update_data(exclude_keywords=message.text.strip())
    await state.set_state(AddFilterStates.min_price)
    await message.answer(
        "💰 Шаг 4/8: Введите <b>минимальную цену</b> (в рублях)\n\n"
        "Пример: 50000",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )


@router.callback_query(F.data == "skip", AddFilterStates.min_price)
async def skip_min_price(callback: CallbackQuery, state: FSMContext):
    await state.update_data(min_price=None)
    await state.set_state(AddFilterStates.max_price)
    await callback.message.edit_text(
        "💰 Шаг 5/8: Введите <b>максимальную цену</b> (в рублях)\n\n"
        "Пример: 15000000",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )
    await callback.answer()


@router.message(AddFilterStates.min_price)
async def process_min_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(" ", "").replace(",", "."))
        await state.update_data(min_price=price)
    except ValueError:
        await message.answer("❌ Введите число. Например: 50000")
        return

    await state.set_state(AddFilterStates.max_price)
    await message.answer(
        "💰 Шаг 5/8: Введите <b>максимальную цену</b> (в рублях)\n\n"
        "Пример: 15000000",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )


@router.callback_query(F.data == "skip", AddFilterStates.max_price)
async def skip_max_price(callback: CallbackQuery, state: FSMContext):
    await state.update_data(max_price=None)
    await state.set_state(AddFilterStates.regions)
    await callback.message.edit_text(
        "📍 Шаг 6/8: Введите <b>регион(ы)</b> через запятую\n\n"
        "Пример: Хабаровский край, Приморский край, ЕАО, Сахалин",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )
    await callback.answer()


@router.message(AddFilterStates.max_price)
async def process_max_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(" ", "").replace(",", "."))
        await state.update_data(max_price=price)
    except ValueError:
        await message.answer("❌ Введите число. Например: 15000000")
        return

    await state.set_state(AddFilterStates.regions)
    await message.answer(
        "📍 Шаг 6/8: Введите <b>регион(ы)</b> через запятую\n\n"
        "Пример: Хабаровский край, Приморский край, ЕАО, Сахалин",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )


@router.callback_query(F.data == "skip", AddFilterStates.regions)
async def skip_regions(callback: CallbackQuery, state: FSMContext):
    await state.update_data(regions=None)
    await state.set_state(AddFilterStates.law_type)
    await callback.message.edit_text(
        "📜 Шаг 7/8: Выберите <b>тип закона</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=law_type_keyboard(),
    )
    await callback.answer()


@router.message(AddFilterStates.regions)
async def process_regions(message: Message, state: FSMContext):
    await state.update_data(regions=message.text.strip())
    await state.set_state(AddFilterStates.law_type)
    await message.answer(
        "📜 Шаг 7/8: Выберите <b>тип закона</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=law_type_keyboard(),
    )


@router.callback_query(F.data.startswith("law_"), AddFilterStates.law_type)
async def process_law_type(callback: CallbackQuery, state: FSMContext):
    law = callback.data.replace("law_", "")
    if law == "all":
        law = None
    await state.update_data(law_type=law)

    await state.set_state(AddFilterStates.okpd2)
    await callback.message.edit_text(
        "📊 Шаг 8/8: Введите <b>коды ОКПД2</b>\n\n"
        "Если не знаете — просто нажмите «⏭ Пропустить этот шаг»",
        parse_mode=ParseMode.HTML,
        reply_markup=skip_keyboard(),
    )
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

    summary = "📋 <b>Проверьте ваш фильтр:</b>\n\n"
    summary += f"📌 Название: <b>{data.get('name', '-')}</b>\n"

    if data.get("keywords"):
        summary += f"🔍 Ключевые слова: {data['keywords']}\n"
    if data.get("exclude_keywords"):
        summary += f"🚫 Исключения: {data['exclude_keywords']}\n"
    if data.get("min_price") is not None:
        summary += f"💰 Мин. цена: {data['min_price']:,.0f} ₽\n"
    if data.get("max_price") is not None:
        summary += f"💰 Макс. цена: {data['max_price']:,.0f} ₽\n"
    if data.get("regions"):
        summary += f"📍 Регионы: {data['regions']}\n"
    if data.get("law_type"):
        summary += f"📜 Закон: {data['law_type']}-ФЗ\n"

    summary += "\nСохраняем?"

    await message.answer(
        summary, parse_mode=ParseMode.HTML, reply_markup=confirm_keyboard()
    )


@router.callback_query(F.data == "confirm_save", AddFilterStates.confirm)
async def save_filter(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    filter_data = {
        "name": data.get("name", "Без названия"),
        "keywords": data.get("keywords"),
        "exclude_keywords": data.get("exclude_keywords"),
        "min_price": data.get("min_price"),
        "max_price": data.get("max_price"),
        "regions": data.get("regions"),
        "law_type": data.get("law_type"),
        "okpd2_codes": data.get("okpd2_codes"),
    }

    new_filter = await add_filter(callback.from_user.id, filter_data)
    await state.clear()

    await callback.message.edit_text(
        f"✅ Фильтр <b>«{filter_data['name']}»</b> успешно сохранен!\n\n"
        f"Бот будет автоматически сканировать закупки каждые 30 минут.",
        parse_mode=ParseMode.HTML,
    )
    await callback.message.answer("Выберите действие:", reply_markup=main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel", AddFilterStates.confirm)
async def cancel_filter(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание фильтра отменено.")
    await callback.message.answer("Выберите действие:", reply_markup=main_keyboard())
    await callback.answer()


# === Мои фильтры ===

@router.message(Command("my_filters"))
@router.message(F.text == "🔍 Мои фильтры")
async def show_filters(message: Message):
    filters = await get_user_filters(message.from_user.id)

    if not filters:
        await message.answer(
            "📭 У вас пока нет созданных фильтров.\n\n"
            "Нажмите «➕ Добавить фильтр» чтобы создать первый.",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer(
        f"📋 <b>Ваши сохраненные фильтры ({len(filters)}):</b>",
        parse_mode=ParseMode.HTML,
    )

    for f in filters:
        text = format_filter_info(f)
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=filter_actions_keyboard(f.id),
        )


@router.callback_query(F.data.startswith("delete_filter_"))
async def process_delete_filter(callback: CallbackQuery):
    filter_id = int(callback.data.replace("delete_filter_", ""))
    success = await delete_filter(filter_id, callback.from_user.id)

    if success:
        await callback.message.edit_text("🗑 Фильтр успешно удалён!")
    else:
        await callback.message.edit_text("❌ Фильтр не найден.")
    await callback.answer()


# === Ручная проверка ===

@router.message(Command("check"))
@router.message(F.text == "🔄 Проверить сейчас")
async def manual_check(message: Message):
    filters = await get_user_filters(message.from_user.id)

    if not filters:
        await message.answer(
            "📭 Сначала создайте хотя бы один фильтр по кнопке «➕ Добавить фильтр».",
            reply_markup=main_keyboard(),
        )
        return

    status_msg = await message.answer(
        "🔄 Запущен сканер закупок...\n"
        "Пожалуйста, подождите немного ⏳",
    )

    checker: PurchaseChecker = message.bot.__dict__.get("purchase_checker")
    if checker:
        count = await checker.manual_check(message.from_user.id)
        await status_msg.edit_text(
            f"✅ Проверка завершена!\n"
            f"Прислано новых релевантных закупок: <b>{count}</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await status_msg.edit_text("❌ Сервис проверки временно недоступен.")


# === Быстрый поиск ===

@router.message(Command("search"))
@router.message(F.text == "🔎 Быстрый поиск")
async def start_quick_search(message: Message, state: FSMContext):
    await state.set_state(QuickSearchStates.query)
    await message.answer(
        "🔎 Введите ключевое слово или фразу для быстрого поиска:\n\n"
        "Пример: сантехника или капремонт",
        reply_markup=cancel_keyboard(),
    )


@router.message(QuickSearchStates.query)
async def process_quick_search(message: Message, state: FSMContext):
    query = message.text.strip()
    await state.clear()

    status_msg = await message.answer(f"🔍 Ищу закупки по запросу «{query}»...", reply_markup=main_keyboard())

    parser = ZakupkiParser()
    try:
        purchases = await parser.search_purchases(keywords=query, days_back=30)

        if not purchases:
            await status_msg.edit_text(
                f"😔 По запросу «{query}» ничего не найдено.\nПопробуйте изменить слово.",
            )
        else:
            await status_msg.edit_text(
                f"✅ Найдено закупок: <b>{len(purchases)}</b>\nПоказываю первые {min(len(purchases), 5)}:",
                parse_mode=ParseMode.HTML,
            )

            for purchase in purchases[:5]:
                await cache_purchase(purchase)
                text = format_purchase(purchase)
                markup = await get_purchase_markup(message.from_user.id, purchase)

                await message.answer(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
                await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Ошибка быстрого поиска: {e}")
        await status_msg.edit_text("❌ Ошибка при поиске. Попробуйте позже.")
    finally:
        await parser.close()


# === Настройки ===

@router.message(F.text == "⚙️ Настройки")
async def settings(message: Message):
    from config import CHECK_INTERVAL

    filters = await get_user_filters(message.from_user.id)

    text = (
        "⚙️ <b>Настройки системы</b>\n\n"
        f"📊 Ваши фильтры: {len(filters)}\n"
        f"⏱ Авто-проверка: каждые {CHECK_INTERVAL} мин.\n"
    )

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


# === Регистрация меню в Telegram ===

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="my_filters", description="Мои фильтры"),
        BotCommand(command="favorites", description="Избранное"),
        BotCommand(command="check", description="Проверить закупки"),
        BotCommand(command="help", description="Справка и помощь"),
    ]
    await bot.set_my_commands(commands)


# === Main ===

async def main():
    print("!!! ЗАПУСК БОТА В МОСКВЕ !!!")
    await init_db()

    if not BOT_TOKEN or "ВАШ_ТОКЕН" in BOT_TOKEN:
        print("❌ ОШИБКА: Токен бота не найден в переменных окружения!")
        logger.error("Токен бота не найден!")
        return

    # Обычная чистая сессия с IPv4 и официальным API
    session = IPv4AiohttpSession(timeout=30.0)
    bot = Bot(token=BOT_TOKEN, session=session)

    try:
        try:
            await set_bot_commands(bot)
            print("✅ Официальное меню команд Telegram установлено!")
        except Exception as e:
            logger.warning(f"Пропущена установка меню команд: {e}")

        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        dp.include_router(router)

        checker = PurchaseChecker(bot)
        bot.__dict__["purchase_checker"] = checker
        await checker.start()

        print("🚀🚀🚀 БОТ УСПЕШНО ЗАПУЩЕН И ГОТОВ К РАБОТЕ! 🚀🚀🚀")
        logger.info("Бот запущен и готов к работе!")

        # Подавляем любые потенциальные сетевые сбои вебхука
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logger.warning(f"Игнорируем ошибку delete_webhook: {e}")

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    finally:
        if "purchase_checker" in bot.__dict__:
            try:
                await bot.__dict__["purchase_checker"].stop()
            except Exception:
                pass
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
