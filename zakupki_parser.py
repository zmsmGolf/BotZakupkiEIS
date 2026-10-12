import aiohttp
import asyncio
import re
import socket
import ssl
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class Purchase:
    """Модель закупки"""
    number: str
    title: str
    customer: str = ""
    price: float = 0.0
    region: str = ""
    law_type: str = ""
    publish_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    url: str = ""
    description: str = ""
    okpd2: str = ""
    status: str = ""


class ZakupkiParser:
    """Парсер для zakupki.gov.ru с поддержкой больших таймаутов и заголовков Chrome"""

    BASE_URL = "https://zakupki.gov.ru"
    SEARCH_URL = f"{BASE_URL}/epz/order/extendedsearch/results.html"

    # Полноценные заголовки современного браузера Chrome
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    REGION_CODES = {
        "хабаровский": "5243009",
        "хабаровск": "5243009",
        "приморский": "5243019",
        "приморье": "5243019",
        "владивосток": "5243019",
        "еврейская": "5243006",
        "еао": "5243006",
        "биробиджан": "5243006",
        "сахалинская": "5243021",
        "сахалин": "5243021",
        "южно-сахалинск": "5243021",
        "амурская": "5243002",
        "забайкальский": "5243007",
    }

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            # Увеличиваем время ожидания ответа от закупков до 60 секунд
            timeout = aiohttp.ClientTimeout(total=60, connect=25, sock_read=45)
            
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET,
                ssl=False
            )
            
            self.session = aiohttp.ClientSession(
                headers=self.HEADERS,
                timeout=timeout,
                connector=connector
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _fetch_page(self, url: str, params: list, retries: int = 2) -> str:
        """Безопасный запрос с повторными попытками при торможении сайта"""
        for attempt in range(1, retries + 1):
            try:
                session = await self._get_session()
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        logger.warning(f"Статус ответа {response.status} на попытке {attempt}")
            except Exception as e:
                logger.warning(f"Попытка {attempt}/{retries} не удалась ({type(e).__name__}). Повтор...")
                if attempt < retries:
                    await asyncio.sleep(2)
        return ""

    async def search_purchases(
        self,
        keywords: str = "",
        exclude_keywords: str = "",
        min_price: float = None,
        max_price: float = None,
        regions: list[str] = None,
        customer_name: str = "",
        law_type: str = "",
        okpd2_codes: list[str] = None,
        days_back: int = 30,
        page: int = 1,
    ) -> list[Purchase]:
        purchases_dict = {}
        max_pages = 50

        logger.info(f"Запуск глубокого парсинга (до {max_pages} страниц)...")

        for current_page in range(1, max_pages + 1):
            params = self._build_search_params(
                min_price=min_price,
                max_price=max_price,
                regions=regions,
                customer_name=customer_name,
                law_type=law_type,
                page=current_page,
            )

            try:
                html = await self._fetch_page(self.SEARCH_URL, params)
                if not html:
                    logger.warning(f"Не удалось получить страницу {current_page}. Завершение сканирования.")
                    break

                page_items = self._parse_search_results(html)

                if not page_items:
                    logger.info(f"Достигнут конец выдачи на странице {current_page - 1}.")
                    break

                for item in page_items:
                    if item.number not in purchases_dict:
                        purchases_dict[item.number] = item

                if current_page % 10 == 0:
                    logger.info(f"Обработано страниц: {current_page}/{max_pages}, собрано лотов: {len(purchases_dict)}")

                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"Ошибка при обработке страницы {current_page}: {type(e).__name__} - {e}")
                break

        logger.info(f"Итого просканировано и проанализировано уникальных лотов: {len(purchases_dict)}")
        return list(purchases_dict.values())

    def _build_search_params(
        self,
        min_price: float = None,
        max_price: float = None,
        regions: list[str] = None,
        customer_name: str = "",
        law_type: str = "",
        page: int = 1,
    ) -> List[Tuple[str, str]]:
        
        params = [
            ("searchString", ""),
            ("morphology", "on"),
            ("search-filter", "Дате размещения"),
            ("pageNumber", str(page)),
            ("sortDirection", "false"),
            ("recordsPerPage", "_50"),
            ("showLotsInfoHidden", "false"),
            ("sortBy", "UPDATE_DATE"),
            ("af", "on"),
        ]

        if law_type == "44":
            params.append(("fz44", "on"))
        elif law_type == "223":
            params.append(("fz223", "on"))
        else:
            params.append(("fz44", "on"))
            params.append(("fz223", "on"))

        if min_price is not None:
            params.append(("priceFromGeneral", str(int(min_price))))
        if max_price is not None:
            params.append(("priceToGeneral", str(int(max_price))))

        if regions:
            added_codes = set()
            for reg in regions:
                clean_reg = reg.strip().lower()
                for key, code in self.REGION_CODES.items():
                    if key in clean_reg and code not in added_codes:
                        params.append(("regions", code))
                        added_codes.add(code)

        if customer_name:
            params.append(("customerPlace", customer_name))

        return params

    def _parse_search_results(self, html: str) -> list[Purchase]:
        purchases = []
        soup = BeautifulSoup(html, "html.parser")

        blocks = soup.find_all("div", class_="search-registry-entry-block")
        if not blocks:
            blocks = soup.find_all("div", class_="row no-gutters registry-entry__form")

        for block in blocks:
            try:
                purchase = self._parse_purchase_block(block)
                if purchase:
                    purchases.append(purchase)
            except Exception as e:
                logger.error(f"Ошибка парсинга блока: {e}")
                continue

        return purchases

    def _parse_purchase_block(self, block) -> Optional[Purchase]:
        number_elem = block.find("div", class_="registry-entry__header-mid__number")
        if not number_elem:
            number_elem = block.find("a", href=re.compile(r"regNumber="))

        if not number_elem:
            return None

        number_text = number_elem.get_text(strip=True)
        number = re.sub(r'[^\d]', '', number_text)
        if not number:
            return None

        url = ""
        link = number_elem.find("a") if number_elem.name != "a" else number_elem
        if link and link.get("href"):
            href = link["href"]
            if not href.startswith("http"):
                href = self.BASE_URL + href
            url = href

        title = ""
        title_elem = block.find("div", class_="registry-entry__body-value")
        if title_elem:
            title = title_elem.get_text(separator=" ", strip=True)

        customer = ""
        cust_elem = block.find("div", class_="registry-entry__body-href")
        if cust_elem:
            customer = cust_elem.get_text(separator=" ", strip=True)

        price = 0.0
        price_elem = block.find("div", class_="price-block__value")
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price_text = re.sub(r'[^\d.,]', '', price_text).replace(",", ".")
            try:
                price = float(price_text)
            except ValueError:
                price = 0.0

        end_date = None
        dates_blocks = block.find_all("div", class_="data-block")
        for db in dates_blocks:
            title_d = db.find("div", class_="data-block__title")
            val_d = db.find("div", class_="data-block__value")
            if title_d and val_d and "окончан" in title_d.get_text().lower():
                d_text = val_d.get_text(strip=True)
                match = re.search(r"(\d{2}\.\d{2}\.\d{4})", d_text)
                if match:
                    try:
                        end_date = datetime.strptime(match.group(1), "%d.%m.%Y")
                    except ValueError:
                        pass
                break

        if not end_date:
            dates = block.find_all("div", class_="data-block__value")
            for d in dates:
                d_text = d.get_text(strip=True)
                match = re.search(r"(\d{2}\.\d{2}\.\d{4})", d_text)
                if match:
                    try:
                        parsed = datetime.strptime(match.group(1), "%d.%m.%Y")
                        if not end_date or parsed > end_date:
                            end_date = parsed
                    except ValueError:
                        pass

        law_type = ""
        law_elem = block.find("div", class_="registry-entry__header-mid__title")
        if law_elem:
            law_text = law_elem.get_text(strip=True)
            if "44" in law_text:
                law_type = "44-ФЗ"
            elif "223" in law_text:
                law_type = "223-ФЗ"

        return Purchase(
            number=number,
            title=title[:500] if title else "Без названия",
            customer=customer[:300] if customer else "",
            price=price,
            region=customer[:300],
            law_type=law_type,
            end_date=end_date,
            url=url or f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={number}",
        )
