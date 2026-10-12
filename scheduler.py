import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from zakupki_parser import ZakupkiParser, Purchase
from filters_manager import matches_filter, format_purchase
from database import (
    get_all_active_users,
    get_user_filters,
    is_purchase_sent,
    mark_purchase_sent,
    get_or_create_user,
    cache_purchase,
    is_favorite,
)
from config import CHECK_INTERVAL
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


async def get_purchase_markup(telegram_id: int, purchase: Purchase) -> InlineKeyboardMarkup:
    """Создает клавиатуру со ссылкой и кнопкой 'В избранное'"""
    is_fav = await is_favorite(telegram_id, purchase.number)
    fav_text = "❤️ В избранном" if is_fav else "⭐️ В избранное"
    fav_callback = f"fav_rem_{purchase.number}" if is_fav else f"fav_add_{purchase.number}"

    buttons = []
    if purchase.url:
        buttons.append(InlineKeyboardButton(text="🔗 Сайт", url=purchase.url))
    buttons.append(InlineKeyboardButton(text=fav_text, callback_data=fav_callback))

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


class PurchaseChecker:
    """Периодическая проверка новых закупок"""

    def __init__(self, bot):
        self.bot = bot
        self.parser = ZakupkiParser()
        self.scheduler = AsyncIOScheduler()
        self._running = False

    async def start(self):
        self.scheduler.add_job(
            self.check_all_users,
            trigger=IntervalTrigger(minutes=CHECK_INTERVAL),
            id="check_purchases",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        self._running = True
        logger.info(f"Планировщик запущен. Проверка каждые {CHECK_INTERVAL} мин.")

    async def stop(self):
        if self._running:
            self.scheduler.shutdown(wait=False)
            await self.parser.close()
            self._running = False
            logger.info("Планировщик остановлен")

    async def check_all_users(self):
        logger.info("Начинаем автоматическую проверку (глубина 50 страниц / 2500 лотов)...")
        try:
            users = await get_all_active_users()
            for user in users:
                try:
                    await self.check_user_filters(user)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Ошибка проверки для пользователя {user.telegram_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка в check_all_users: {e}")
        logger.info("Автоматическая проверка завершена")

    async def check_user_filters(self, user):
        filters = await get_user_filters(user.telegram_id)
        if not filters:
            return

        for user_filter in filters:
            if not user_filter.is_active:
                continue

            try:
                regions = None
                if user_filter.regions:
                    regions = [r.strip() for r in user_filter.regions.split(",")]

                purchases = await self.parser.search_purchases(
                    keywords=user_filter.keywords or "",
                    exclude_keywords=user_filter.exclude_keywords or "",
                    min_price=user_filter.min_price,
                    max_price=user_filter.max_price,
                    regions=regions,
                    customer_name=user_filter.customer_name or "",
                    law_type=user_filter.law_type or "",
                )

                sent_count = 0
                for purchase in purchases:
                    if matches_filter(purchase, user_filter):
                        if not await is_purchase_sent(user.id, purchase.number):
                            try:
                                await cache_purchase(purchase)

                                text = format_purchase(purchase)
                                text += f"\n🏷 Фильтр: {user_filter.name}"

                                markup = await get_purchase_markup(user.telegram_id, purchase)

                                await self.bot.send_message(
                                    user.telegram_id,
                                    text,
                                    parse_mode="HTML",
                                    reply_markup=markup,
                                    disable_web_page_preview=True,
                                )
                                await mark_purchase_sent(user.id, purchase.number)
                                sent_count += 1
                                await asyncio.sleep(0.35)

                                if sent_count >= 100:
                                    break

                            except Exception as e:
                                logger.error(f"Ошибка отправки: {e}")

                await asyncio.sleep(1.5)

            except Exception as e:
                logger.error(f"Ошибка обработки фильтра {user_filter.id}: {e}")

    async def manual_check(self, telegram_id: int) -> int:
        user = await get_or_create_user(telegram_id)
        filters = await get_user_filters(telegram_id)

        if not filters:
            return 0

        total_sent = 0

        for user_filter in filters:
            if not user_filter.is_active:
                continue

            regions = None
            if user_filter.regions:
                regions = [r.strip() for r in user_filter.regions.split(",")]

            purchases = await self.parser.search_purchases(
                keywords=user_filter.keywords or "",
                exclude_keywords=user_filter.exclude_keywords or "",
                min_price=user_filter.min_price,
                max_price=user_filter.max_price,
                regions=regions,
                customer_name=user_filter.customer_name or "",
                law_type=user_filter.law_type or "",
            )

            for purchase in purchases:
                if matches_filter(purchase, user_filter):
                    if not await is_purchase_sent(user.id, purchase.number):
                        try:
                            await cache_purchase(purchase)

                            text = format_purchase(purchase)
                            text += f"\n🏷 Фильтр: {user_filter.name}"

                            markup = await get_purchase_markup(telegram_id, purchase)

                            await self.bot.send_message(
                                telegram_id,
                                text,
                                parse_mode="HTML",
                                reply_markup=markup,
                                disable_web_page_preview=True,
                            )
                            await mark_purchase_sent(user.id, purchase.number)
                            total_sent += 1
                            await asyncio.sleep(0.35)

                            if total_sent >= 100:
                                return total_sent
                        except Exception as e:
                            logger.error(f"Ошибка отправки: {e}")

            await asyncio.sleep(1.5)

        return total_sent