import aiohttp
import asyncio
import re
import socket
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)

@dataclass
class Purchase:
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

class ZakupkiParser:
    BASE_URL = "https://zakupki.gov.ru"
    SEARCH_URL = f"{BASE_URL}/epz/order/extendedsearch/results.html"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Connection": "keep-alive"
    }

    REGION_CODES = {
        "хабаровский": "5243009", "хабаровск": "5243009", "приморский": "5243019",
        "приморье": "5243019", "владивосток": "5243019", "еврейская": "5243006",
        "еао": "5243006", "биробиджан": "5243006", "сахалинская": "5243021",
        "сахалин": "5243021", "амурская": "5243002", "забайкальский": "5243007"
    }

    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)
            self.session = aiohttp.ClientSession(headers=self.HEADERS, connector=connector, timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def search_purchases(self, keywords="", min_price=None, max_price=None, regions=None, law_type="", **kwargs):
        purchases_dict = {}
        # Сканируем 15 страниц для баланса скорости и глубины
        for page in range(1, 16):
            params = [
                ("searchString", ""), ("morphology", "on"), ("pageNumber", str(page)),
                ("sortDirection", "false"), ("recordsPerPage", "_20"), ("sortBy", "UPDATE_DATE"), ("af", "on")
            ]
            if regions:
                for r in regions:
                    for key, code in self.REGION_CODES.items():
                        if key in r.lower():
                            params.append(("selectedSubjectsIdNameCodeList", code))
                            params.append((f"selectedSubjectsIdNameCodeList_{code}", code))
            
            try:
                session = await self._get_session()
                async with session.get(self.SEARCH_URL, params=params) as resp:
                    if resp.status != 200: break
                    soup = BeautifulSoup(await resp.text(), "html.parser")
                    blocks = soup.find_all("div", class_="search-registry-entry-block")
                    if not blocks: break
                    
                    for block in blocks:
                        p = self._parse_block(block)
                        if p and p.number not in purchases_dict:
                            purchases_dict[p.number] = p
                await asyncio.sleep(0.3)
            except: break
        return list(purchases_dict.values())

    def _parse_block(self, block):
        try:
            num_tag = block.find("div", class_="registry-entry__header-mid__number").find("a")
            number = re.sub(r'[^\d]', '', num_tag.text)
            url = self.BASE_URL + num_tag["href"] if not num_tag["href"].startswith("http") else num_tag["href"]
            title = block.find("div", class_="registry-entry__body-value").text.strip()
            price_text = block.find("div", class_="price-block__value").text.strip()
            price = float(re.sub(r'[^\d.,]', '', price_text).replace(",", "."))
            
            # Дата окончания
            end_date = None
            date_val = block.find("div", class_="data-block__value")
            if date_val:
                match = re.search(r"(\d{2}\.\d{2}\.\d{4})", date_val.text)
                if match: end_date = datetime.strptime(match.group(1), "%d.%m.%Y")

            return Purchase(number=number, title=title, price=price, url=url, end_date=end_date)
        except: return None
