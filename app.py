# -*- coding: utf-8 -*-
"""
app.py
Объединённый скрипт: Playwright для tour-kassa; requests.Session для остальных сайтов.
Сохраняет cookies Playwright в папку playwright_sessions для повторного использования.
"""

import os
import json
import time
import random
import logging
import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import re

import boto3
from botocore.exceptions import ClientError

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Playwright async API
from playwright.async_api import async_playwright, Browser, Page

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scraper")

class CurrencyScraperError(Exception):
    '''Кастомное исключение для ошибок скреппинга'''
    pass

# Папка для хранения persistent context (Playwright)
PLAYWRIGHT_USER_DATA_DIR = Path("playwright_sessions")
PLAYWRIGHT_USER_DATA_DIR.mkdir(exist_ok=True)

# Настройки
SELENIUM_WAIT_SECONDS = int(os.getenv("SELENIUM_WAIT_SECONDS", "8"))  # используем как задержку для Playwright
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0"
PLAYWRIGHT_CONTEXT_NAME = "tour_kassa_context"  # директория внутри playwright_sessions
PLAYWRIGHT_STORAGE_STATE_PATH = PLAYWRIGHT_USER_DATA_DIR / "storage_state.json"

STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", "https://storage.yandexcloud.net")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET")
STORAGE_STATE_KEY = os.getenv("STORAGE_STATE_KEY", "playwright/storage_state.json")
STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")


def _is_storage_configured() -> bool:
    return all([STORAGE_BUCKET, STORAGE_STATE_KEY, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY])


_storage_client = None


def get_storage_client():
    global _storage_client
    if not _is_storage_configured():
        raise ValueError("Object Storage credentials are not fully configured")
    if _storage_client is None:
        _storage_client = boto3.client(
            "s3",
            endpoint_url=STORAGE_ENDPOINT,
            aws_access_key_id=STORAGE_ACCESS_KEY,
            aws_secret_access_key=STORAGE_SECRET_KEY,
            region_name="ru-central1",
        )
    return _storage_client


def upload_storage_state(local_path: Path) -> None:
    if not _is_storage_configured():
        logger.debug("Skipping storage_state upload — storage is not configured")
        return
    if not local_path.exists():
        logger.warning(f"Cannot upload storage_state: {local_path} does not exist")
        return
    try:
        client = get_storage_client()
        client.put_object(
            Bucket=STORAGE_BUCKET,
            Key=STORAGE_STATE_KEY,
            Body=local_path.read_bytes(),
            ContentType="application/json; charset=utf-8",
        )
        logger.info("storage_state.json uploaded to Object Storage")
    except Exception as exc:
        logger.warning(f"Unable to upload storage_state.json: {exc}")



def refresh_storage_state() -> Optional[Path]:
    """
    Download storage_state.json from Yandex Object Storage if credentials are provided.
    Keeps the previous local copy when refresh fails.
    """
    if not _is_storage_configured():
        return PLAYWRIGHT_STORAGE_STATE_PATH if PLAYWRIGHT_STORAGE_STATE_PATH.exists() else None

    try:
        client = get_storage_client()
        obj = client.get_object(Bucket=STORAGE_BUCKET, Key=STORAGE_STATE_KEY)
        PLAYWRIGHT_STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLAYWRIGHT_STORAGE_STATE_PATH.write_bytes(obj["Body"].read())
        logger.info("Storage state downloaded from object storage")
        return PLAYWRIGHT_STORAGE_STATE_PATH
    except ClientError as exc:
        logger.warning(f"Object storage error while fetching storage_state.json: {exc}")
        return PLAYWRIGHT_STORAGE_STATE_PATH if PLAYWRIGHT_STORAGE_STATE_PATH.exists() else None
    except Exception as exc:
        logger.warning(f"Unable to refresh storage state: {exc}")
        return PLAYWRIGHT_STORAGE_STATE_PATH if PLAYWRIGHT_STORAGE_STATE_PATH.exists() else None



class PlaywrightHelper:
    """
    Асинхронный helper для получения HTML через Playwright и синхронизации storage_state.json с Object Storage.
    """

    STEALTH_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = window.chrome || { runtime: {} };
    """

    def __init__(self, user_agent: Optional[str] = None, headless: bool = True, storage_state_path: Optional[Path] = None):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        self.headless = headless
        self.storage_state_path = storage_state_path

    async def get_page_html(
        self,
        url: str,
        wait_seconds: int = SELENIUM_WAIT_SECONDS,
        wait_selector: Optional[str] = None,
    ) -> Optional[str]:
        """
        Запускает Playwright, открывает Chromium и применяет storage state, чтобы вернуть HTML страницы.
        """
        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context_kwargs = {
                    "viewport": {"width": 1280, "height": 800},
                    "user_agent": self.user_agent,
                    "locale": "ru-RU",
                    "timezone_id": "Europe/Moscow",
                }
                if self.storage_state_path and self.storage_state_path.exists():
                    context_kwargs["storage_state"] = str(self.storage_state_path)

                context = await browser.new_context(**context_kwargs)
                await context.add_init_script(self.STEALTH_INIT_SCRIPT)
                await context.set_extra_http_headers(
                    {"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8"}
                )

                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=90000)

                if wait_selector:
                    await page.wait_for_selector(
                        wait_selector, timeout=max(wait_seconds, 3) * 1000
                    )
                else:
                    await page.wait_for_load_state("networkidle")

                await asyncio.sleep(random.uniform(wait_seconds, wait_seconds + 3))
                html = await page.content()

                if self.storage_state_path:
                    try:
                        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                        await context.storage_state(path=str(self.storage_state_path))
                        upload_storage_state(self.storage_state_path)
                    except Exception as storage_exc:
                        logger.warning(f"Failed to persist storage_state.json: {storage_exc}")

                return html
        except Exception as e:
            logger.warning(f"Playwright error for {url}: {e}")
            return None
        finally:
            if context:
                with suppress(Exception):
                    await context.close()
            if browser:
                with suppress(Exception):
                    await browser.close()

    def fetch(
        self,
        url: str,
        wait_seconds: int = SELENIUM_WAIT_SECONDS,
        wait_selector: Optional[str] = None,
    ) -> Optional[str]:
        """
        Синхронная обертка — запускает асинхронный Playwright из текущего event loop.
        """
        try:
            return asyncio.run(
                self.get_page_html(
                    url,
                    wait_seconds=wait_seconds,
                    wait_selector=wait_selector,
                )
            )
        except Exception:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.get_page_html(
                        url,
                        wait_seconds=wait_seconds,
                        wait_selector=wait_selector,
                    )
                )
                loop.close()
                return result
            except Exception as ee:
                logger.error(f"Failed to run Playwright loop: {ee}")
                return None

class CurrencyScraper:
    """
    Основной скрапер — использует requests.Session для большинства сайтов и PlaywrightHelper для
    tour-kassa.ru (и похожих с JS-челленджами).
    """

    def __init__(self):
        self.session = requests.Session()
        self.results: List[Dict] = []
        self.errors: List[str] = []
        self.storage_state_path = refresh_storage_state()
        self.playwright = PlaywrightHelper(
            headless=PLAYWRIGHT_HEADLESS,
            storage_state_path=self.storage_state_path,
        )
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:116.0) Gecko/20100101 Firefox/116.0'
        ]

    def get_random_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    def extract_rate(self, text: str) -> Optional[str]:
        if not text or text.strip() == '-':
            return None
        patterns = [r'(\d+[.,]\d+)', r'(\d+\.\d+)', r'(\d+,\d+)', r'(\d+)']
        compact = text.replace(' ', '')
        for pattern in patterns:
            m = re.search(pattern, compact)
            if m:
                return m.group(1).replace(',', '.')
        return None
    
    def make_request(self, url: str, retries: int = 3, timeout: int = 120) -> Optional[BeautifulSoup]:
        """
        Для tour-kassa.ru используем Playwright, для остальных сайтов — requests.Session.
        Возвращает BeautifulSoup либо None.
        """
        for attempt in range(retries):
            try:
                headers = self.get_random_headers()

                if 'tour-kassa.ru' in url:
                    logger.info(f"Using Playwright for {url} (attempt {attempt+1})")
                    html = self.playwright.fetch(
                        url,
                        wait_selector='table.mod_rate_today',
                    )
                    if not html:
                        raise Exception("Playwright failed to fetch HTML")

                    lower = html.lower()
                    challenge_tokens = [
                        'Пожалуйста подтвердите, что вы человек',
                        'Похоже, что вы робот',
                        'js-challenge',
                        'cf-chl',
                        'attention required',
                    ]
                    if any(token in lower for token in challenge_tokens):
                        raise Exception("Playwright returned interstitial / challenge page")

                    return BeautifulSoup(html, 'html.parser')

                if 'cruclub.ru' in url:
                    temp_session = requests.Session()
                    temp_session.headers.update({
                        'User-Agent': headers.get('User-Agent', 'Mozilla/5.0'),
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
                        'Accept-Encoding': 'identity',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    })
                    resp = temp_session.get(url, timeout=timeout, verify=False)
                    temp_session.close()
                else:
                    verify_ssl = 'tourtrans.ru' not in url
                    resp = self.session.get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        verify=verify_ssl,
                    )

                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                time.sleep(random.uniform(0.8, 2.0))
                return BeautifulSoup(resp.content, 'html.parser')

            except Exception as e:
                logger.warning(f"Attempt {attempt+1} for {url} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(random.uniform(2, 5))
                    continue
                else:
                    self.errors.append(f"Failed to fetch {url}: {e}")
                    return None

    def scrape_tour_kassa_site(self, url: str):
        """
        Пример парсинга таблицы tour-kassa (использует make_request с Playwright).
        """
        soup = self.make_request(url)
        if not soup:
            return []
        
        results = []
        
        # Конфигурация туроператоров
        operators = [
            {'id': 3153, 'sectionId': 539, 'name': 'EUR', 'touroperator': 'ЦБ РФ'},
            {'id': 3167, 'sectionId': 539, 'name': 'USD', 'touroperator': 'ЦБ РФ'},
            {'id': 3141, 'sectionId': 527, 'name': 'EUR', 'touroperator': 'Корал Тревел'},
            {'id': 3155, 'sectionId': 527, 'name': 'USD', 'touroperator': 'Корал Тревел'},
            {'id': 3147, 'sectionId': 531, 'name': 'EUR', 'touroperator': 'Санмар'},
            {'id': 3161, 'sectionId': 531, 'name': 'USD', 'touroperator': 'Санмар'},
            {'id': 3151, 'sectionId': 535, 'name': 'EUR', 'touroperator': 'Фан & Сан'},
            {'id': 3165, 'sectionId': 535, 'name': 'USD', 'touroperator': 'Фан & Сан'},
            {'id': 3129, 'sectionId': 521, 'name': 'EUR', 'touroperator': 'Анекс Тур'},
            {'id': 3131, 'sectionId': 521, 'name': 'USD', 'touroperator': 'Анекс Тур'},
            {'id': 3143, 'sectionId': 529, 'name': 'EUR', 'touroperator': 'Пегас Туристик'},
            {'id': 3157, 'sectionId': 529, 'name': 'USD', 'touroperator': 'Пегас Туристик'},
            {'id': 3145, 'sectionId': 537, 'name': 'EUR', 'touroperator': 'Русский Экспресс'},
            {'id': 3159, 'sectionId': 537, 'name': 'USD', 'touroperator': 'Русский Экспресс'},
            {'id': 3133, 'sectionId': 523, 'name': 'EUR', 'touroperator': 'Библио Глобус'},
            {'id': 3135, 'sectionId': 523, 'name': 'USD', 'touroperator': 'Библио Глобус'},
            {'id': 3137, 'sectionId': 525, 'name': 'EUR', 'touroperator': 'Интурист'},
            {'id': 3139, 'sectionId': 525, 'name': 'USD', 'touroperator': 'Интурист'},
            {'id': 3149, 'sectionId': 533, 'name': 'EUR', 'touroperator': 'Тез-Тур'},
            {'id': 3163, 'sectionId': 533, 'name': 'USD', 'touroperator': 'Тез-Тур'},
            {'id': 17561, 'sectionId': 665, 'name': 'EUR', 'touroperator': 'Лоти'},
            {'id': 17563, 'sectionId': 665, 'name': 'USD', 'touroperator': 'Лоти'}
        ]

        table = soup.find('table', class_='mod_rate_today')
        if not table:
            logger.error("mod_rate_today table not found on tour-kassa")
            return []

        # Группировка операторов
        operator_groups = {}
        for op in operators:
            if op['touroperator'] not in operator_groups:
                operator_groups[op['touroperator']] = []
            operator_groups[op['touroperator']].append(op)
        
        # Обработка каждого оператора
        for operator_name, operator_items in operator_groups.items():
            operator_data = self._get_exchange_rates_by_operator(table, operator_name)
            
            if operator_data:
                for item in operator_items:
                    currency_data = operator_data['EUR'] if item['name'] == 'EUR' else operator_data['USD']
                    
                    results.append({
                        'id': item['id'],
                        'sectionId': item['sectionId'],
                        'name': item['name'],
                        'touroperator': item['touroperator'],
                        'rate': currency_data['rate'],
                        'percentToCb': currency_data['percentage'],
                        'delta': currency_data['delta']
                    })
        
        return results
    
    def _get_exchange_rates_by_operator(self, table: BeautifulSoup, operator_name: str) -> Optional[Dict]:
        '''Извлекает блоки с курсами конкретного туроператора'''
        rows = table.find_all('tr')
        target_name = self._normalize_operator_name(operator_name)

        for row in rows:
            operator_cell = row.find('td', class_='mod_rate_oper')
            if not operator_cell:
                continue

            div_element = operator_cell.find('div')
            if not div_element:
                continue

            operator_text = div_element.get_text(strip=True).split('\n')[0].strip()
            normalized_operator = self._normalize_operator_name(operator_text)

            if (
                normalized_operator == target_name
                or target_name in normalized_operator
                or normalized_operator in target_name
            ):
                cells = row.find_all('td')
                if len(cells) >= 7:
                    return {
                        'EUR': {
                            'rate': self.extract_rate(cells[1].get_text(strip=True)),
                            'percentage': cells[2].get_text(strip=True),
                            'delta': cells[3].get_text(strip=True)
                        },
                        'USD': {
                            'rate': self.extract_rate(cells[4].get_text(strip=True)),
                            'percentage': cells[5].get_text(strip=True),
                            'delta': cells[6].get_text(strip=True)
                        },
                    }

        return None

    @staticmethod
    def _normalize_operator_name(name: str) -> str:
        return re.sub(r'\s+', ' ', name).strip().lower()

    def scrape_paks_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта ПАКС'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        currency_div = soup.find('div', class_='page-header__currency')
        if not currency_div or not hasattr(currency_div, 'select_one'):
            raise CurrencyScraperError('Элемент page-header__currency не найден или не является тегом')
        
        eur_element = soup.select_one('div.page-header__currency ul li:nth-child(2) span.page-header__currency-value')
        usd_element = soup.select_one('div.page-header__currency ul li:nth-child(1) span.page-header__currency-value')
        
        return [
            {
                'id': 3727,
                'sectionId': 563,
                'name': 'EUR',
                'touroperator': 'ПАКС',
                'rate': self.extract_rate(eur_element.get_text() if eur_element else ''),
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 3729,
                'sectionId': 563,
                'name': 'USD',
                'touroperator': 'ПАКС',
                'rate': self.extract_rate(usd_element.get_text() if usd_element else ''),
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_pak_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта ПАК'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_div = soup.find('div', class_='mb-10 exchange-rates-block-items')
        if not exchange_div:
            raise CurrencyScraperError('Элемент exchange-rates-block-items не найден')
        
        # Используем soup.select_one с полным CSS-селектором относительно документа
        eur_element = soup.select_one('div.mb-10.exchange-rates-block-items div:nth-child(2) div div.exchange-rates__currencies div:nth-child(1) span:nth-child(1)')
        usd_element = soup.select_one('div.mb-10.exchange-rates-block-items div:nth-child(1) div div.exchange-rates__currencies div:nth-child(1) span:nth-child(1)')
        
        return [
            {
                'id': 3873,
                'sectionId': 565,
                'name': 'EUR',
                'touroperator': 'ПАК',
                'rate': self.extract_rate(eur_element.get_text() if eur_element else ''),
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 3875,
                'sectionId': 565,
                'name': 'USD',
                'touroperator': 'ПАК',
                'rate': self.extract_rate(usd_element.get_text() if usd_element else ''),
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_arttour_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Арт Тур'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('#valuta-sl')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('#cur_rates_eur')
        usd_element = soup.select_one('#cur_rates_usd')
        eur_rate = eur_element.get_text().strip() if eur_element else ''
        usd_rate = usd_element.get_text().strip() if usd_element else ''
            
        return [
            {
                'id': 3995,
                'sectionId': 571,
                'name': 'EUR',
                'touroperator': 'Арт Тур',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 3997,
                'sectionId': 571,
                'name': 'USD',
                'touroperator': 'Арт Тур',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_icstrvl_site(self, url: str) -> List[Dict]:
        """Скрапит курсы USD и EUR с сайта ICS Travel"""
        soup = self.make_request(url)
        if not soup:
            return []

        # Множественные стратегии поиска элемента с курсами
        rates_element = None
        
        # Стратегия 1: поиск div с классом rates
        rates_element = soup.find('div', class_='rates')
        
        # Стратегия 2: поиск по тексту "Внутренний курс"
        if not rates_element:
            internal_rate_span = soup.find('span', text=re.compile(r'Внутренний курс'))
            if internal_rate_span:
                rates_element = internal_rate_span.parent
        
        # Стратегия 3: поиск любого элемента содержащего курс USD
        if not rates_element:
            text_elements = soup.find_all(text=re.compile(r'1\s*USD\s*='))
            if text_elements:
                rates_element = text_elements[0].parent
        
        # Стратегия 4: поиск в любом месте страницы
        if not rates_element:
            rates_element = soup
        
        # Получаем HTML код и текст элемента
        html_content = str(rates_element)
        text_content = rates_element.get_text()
        
        logger.debug(f"Найденный текст: {text_content[:200]}")  # Для отладки

        # Ищем курсы с помощью регулярных выражений
        # Поиск в HTML коде (с тегами <b>)
        usd_match = re.search(r'1\s*USD\s*=\s*<b>([\d,]+)</b>', html_content)
        eur_match = re.search(r'1\s*EUR\s*=\s*<b>([\d,]+)</b>', html_content)
        
        # Если не нашли в HTML, ищем в обычном тексте
        if not usd_match:
            usd_match = re.search(r'1\s*USD\s*=\s*([\d,]+)', text_content)
        if not eur_match:
            eur_match = re.search(r'1\s*EUR\s*=\s*([\d,]+)', text_content)

        # Извлекаем и конвертируем значения
        usd_rate = None
        eur_rate = None
        
        if usd_match:
            usd_str = usd_match.group(1).replace(',', '.')
            try:
                usd_rate = float(usd_str)
            except ValueError:
                logger.debug(f"Ошибка конвертации USD: {usd_str}")
        
        if eur_match:
            eur_str = eur_match.group(1).replace(',', '.')
            try:
                eur_rate = float(eur_str)
            except ValueError:
                logger.debug(f"Ошибка конвертации EUR: {eur_str}")

        logger.debug(f"USD: {usd_rate}, EUR: {eur_rate}")  # Для отладки

        # Возвращаем результат только если найдены оба курса
        if usd_rate is None or eur_rate is None:
            logger.debug("Не удалось извлечь один или оба курса")
            return []

        return [
            {
                'id': 3991,
                'sectionId': 569,
                'name': 'EUR',
                'touroperator': 'ICS',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 3993,
                'sectionId': 569,
                'name': 'USD',
                'touroperator': 'ICS',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_space_travel_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Спейс'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('#header > div > div.new-head > div.vall-st')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('p:nth-child(3) > span.eur')
        usd_element = soup.select_one('p:nth-child(2) > span.usd')
        eur_rate = eur_element.get_text().strip() if eur_element else ''
        usd_rate = usd_element.get_text().strip() if usd_element else ''
            
        return [
            {
                'id': 3999,
                'sectionId': 573,
                'name': 'EUR',
                'touroperator': 'Space',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4001,
                'sectionId': 573,
                'name': 'USD',
                'touroperator': 'Space',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_vand_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Ванда'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('div.header__course.d-none.d-lg-block')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('#wrapper > header > div > div.header__course.d-none.d-lg-block > div > span:nth-child(4) > span')
        usd_element = soup.select_one('#wrapper > header > div > div.header__course.d-none.d-lg-block > div > span:nth-child(3) > span')
        eur_rate = eur_element.get_text().strip() if eur_element else ''
        usd_rate = usd_element.get_text().strip() if usd_element else ''
            
        return [
            {
                'id': 4003,
                'sectionId': 575,
                'name': 'EUR',
                'touroperator': 'Ванд',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4005,
                'sectionId': 575,
                'name': 'USD',
                'touroperator': 'Ванд',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_amigo_tours_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Амиго Турс'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('div.exchRates__cont.header__top__item')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('div:nth-child(1) > span.curr_rate')
        usd_element = soup.select_one('div:nth-child(2) > span.curr_rate')
        eur_text = eur_element.get_text().strip() if eur_element else ''
        usd_text = usd_element.get_text().strip() if usd_element else ''

        eur_match = re.search(r'\d+,\d+', eur_text)
        usd_match = re.search(r'\d+,\d+', usd_text)

        eur_rate = eur_match.group(0) if eur_match else ''
        usd_rate = usd_match.group(0) if usd_match else ''
            
        return [
            {
                'id': 4009,
                'sectionId': 577,
                'name': 'EUR',
                'touroperator': 'Амиго Турс',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4011,
                'sectionId': 577,
                'name': 'USD',
                'touroperator': 'Амиго Турс',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_quinta_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Квинты'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('div.main-container')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('div.main-container header div div:nth-child(1) div:nth-child(3) div.courses div:nth-child(2)')
        usd_element = soup.select_one('div.main-container header div div:nth-child(1) div:nth-child(3) div.courses div:nth-child(3)')
        eur_text = eur_element.get_text().strip() if eur_element else ''
        usd_text = usd_element.get_text().strip() if usd_element else ''

        eur_match = re.search(r'\d+.\d+', eur_text)
        usd_match = re.search(r'\d+.\d+', usd_text)

        eur_rate = eur_match.group(0) if eur_match else ''
        usd_rate = usd_match.group(0) if usd_match else ''
            
        return [
            {
                'id': 4013,
                'sectionId': 579,
                'name': 'EUR',
                'touroperator': 'Квинта',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4015,
                'sectionId': 579,
                'name': 'USD',
                'touroperator': 'Квинта',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_bsigroup_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта BSI'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('div.fright-col')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('div.fright-col div.col__left-30 div div div.cur-drop div:nth-child(2)')
        usd_element = soup.select_one('div.fright-col div.col__left-30 div div div.cur-drop div:nth-child(1)')
        eur_text = eur_element.get_text().strip() if eur_element else ''
        usd_text = usd_element.get_text().strip() if usd_element else ''

        eur_match = re.search(r'\d+.\d+', eur_text)
        usd_match = re.search(r'\d+.\d+', usd_text)

        eur_rate = eur_match.group(0) if eur_match else ''
        usd_rate = usd_match.group(0) if usd_match else ''
            
        return [
            {
                'id': 4017,
                'sectionId': 581,
                'name': 'EUR',
                'touroperator': 'BSI',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4019,
                'sectionId': 581,
                'name': 'USD',
                'touroperator': 'BSI',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_tourtrans_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта ТурТрансВояж'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('div.currency')
        if not exchange_block:
            return []
        
        tomorrow_element = soup.select_one('#left > div.currency > ul > li:nth-child(3) > span')
        today_element = soup.select_one('#left > div.currency > ul > li:nth-child(2) > span')
        
        tomorrow_text = tomorrow_element.get_text().strip() if tomorrow_element else ''
        today_text = today_element.get_text().strip() if today_element else ''

        tomorrow_match = re.search(r'\d+.\d+', tomorrow_text)
        today_match = re.search(r'\d+.\d+', today_text)

        tomorrow_rate = tomorrow_match.group(0) if tomorrow_match else ''
        today_rate = today_match.group(0) if today_match else ''

        rate = tomorrow_rate if tomorrow_rate else today_rate
            
        return [
            {
                'id': 4021,
                'sectionId': 583,
                'name': 'EUR',
                'touroperator': 'ТурТрансВояж',
                'rate': rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4023,
                'sectionId': 583,
                'name': 'USD',
                'touroperator': 'ТурТрансВояж',
                'rate': rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_spectrum_site(self, url: str) -> List[Dict]:
        """Скрапит курсы USD и EUR с сайта Spectrum через API"""
        
        # API endpoints для получения курсов
        usd_api_url = "https://online.spectrum.ru/export/default.php?samo_action=api&version=1.0&oauth_token=5e33b4a9502a46039e5a65e1113b17a1&type=json&action=Currency_RATES&CURRENCY=3&CURRENCYBASE=1"
        eur_api_url = "https://online.spectrum.ru/export/default.php?samo_action=api&version=1.0&oauth_token=5e33b4a9502a46039e5a65e1113b17a1&type=json&action=Currency_RATES&CURRENCY=4&CURRENCYBASE=1"
        
        usd_rate = None
        eur_rate = None
        
        try:
            # Получаем курс USD
            logger.debug("Запрашиваем курс USD...")
            headers = self.get_random_headers() if hasattr(self, 'get_random_headers') else {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            usd_response = self.session.get(usd_api_url, headers=headers, timeout=30)
            usd_response.raise_for_status()
            usd_data = usd_response.json()
            
            logger.debug(f"USD ответ: {usd_data}")
            
            if 'Currency_RATES' in usd_data and len(usd_data['Currency_RATES']) > 0:
                usd_rate = usd_data['Currency_RATES'][0]['rate']
                logger.debug(f"USD курс получен: {usd_rate}")
            
        except Exception as e:
            logger.debug(f"Ошибка при получении курса USD: {str(e)}")
            if hasattr(self, 'errors'):
                self.errors.append(f"Ошибка получения USD курса Spectrum: {str(e)}")
        
        try:
            # Получаем курс EUR
            logger.debug("Запрашиваем курс EUR...")
            
            eur_response = self.session.get(eur_api_url, headers=headers, timeout=30)
            eur_response.raise_for_status()
            eur_data = eur_response.json()
            
            logger.debug(f"EUR ответ: {eur_data}")
            
            if 'Currency_RATES' in eur_data and len(eur_data['Currency_RATES']) > 0:
                eur_rate = eur_data['Currency_RATES'][0]['rate']
                logger.debug(f"EUR курс получен: {eur_rate}")
            
        except Exception as e:
            logger.debug(f"Ошибка при получении курса EUR: {str(e)}")
            if hasattr(self, 'errors'):
                self.errors.append(f"Ошибка получения EUR курса Spectrum: {str(e)}")
        
        logger.debug(f"Финальные курсы - USD: {usd_rate}, EUR: {eur_rate}")
        
        # Возвращаем результат
        return [
            {
                'id': 4025,
                'sectionId': 585,
                'name': 'EUR',
                'touroperator': 'Спектрум',
                'rate': eur_rate if eur_rate else '',
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4027,
                'sectionId': 585,
                'name': 'USD',
                'touroperator': 'Спектрум',
                'rate': usd_rate if usd_rate else '',
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_cruclub_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Краски Мира'''
        soup = self.make_request(url)
        if not soup:
            logger.debug("DEBUG: Не удалось получить soup")
            return []
        
        logger.debug("DEBUG: HTML получен успешно")
        
        # Выводим первые 1000 символов HTML для анализа
        html_text = str(soup)
        logger.debug(f"DEBUG: Первые 1000 символов HTML:")
        logger.debug(html_text[:1000])
        logger.debug("=" * 50)
        
        # Ищем любые упоминания валют в тексте
        all_text = soup.get_text()
        logger.debug(f"DEBUG: Весь текст содержит {len(all_text)} символов")
        
        # Поиск слов "курс", "валют", "USD", "EUR" в тексте
        keywords = ['курс', 'валют', 'USD', 'EUR', 'RUR', 'рубл']
        for keyword in keywords:
            if keyword.lower() in all_text.lower():
                logger.debug(f"DEBUG: Найдено ключевое слово '{keyword}' в тексте")
            else:
                logger.debug(f"DEBUG: Ключевое слово '{keyword}' НЕ найдено")
        
        # Проверяем, есть ли блок с курсами валют
        currency_spans = soup.select('div.win div.body.small.dlist div.item span')
        logger.debug(f"DEBUG: Найдено span элементов: {len(currency_spans)}")
        
        # Выводим все найденные span элементы
        for i, span in enumerate(currency_spans):
            parent_text = span.parent.get_text()
            span_text = span.get_text()
            logger.debug(f"DEBUG: Span {i}: parent='{parent_text}', span='{span_text}'")
        
        # Также попробуем найти блок с заголовком "КУРСЫ ВАЛЮТ"
        currency_headers = soup.find_all(string=lambda text: text and 'КУРСЫ ВАЛЮТ' in text)
        logger.debug(f"DEBUG: Найдено заголовков с 'КУРСЫ ВАЛЮТ': {len(currency_headers)}")

        currency_spans = soup.select('div.win div.body.small.dlist div.item span')
        logger.debug(f"DEBUG: Найдено span элементов: {len(currency_spans)}")
        
        # Попробуем более широкий поиск
        all_spans = soup.find_all('span')
        currency_related_spans = []
        for span in all_spans:
            text = span.get_text()
            if re.search(r'\d+\.\d+', text):
                currency_related_spans.append((span, text))
        
        logger.debug(f"DEBUG: Найдено span с числами: {len(currency_related_spans)}")
        for span, text in currency_related_spans:
            parent_text = span.parent.get_text()
            logger.debug(f"DEBUG: Числовой span: '{text}', parent: '{parent_text}'")
        
        usd_rate = ''
        eur_rate = ''
        
        for span in currency_spans:
            parent_text = span.parent.get_text()
            rate_text = span.get_text().strip()
            
            if 'USD' in parent_text:
                usd_match = re.search(r'\d+\.\d+', rate_text)
                usd_rate = usd_match.group(0) if usd_match else ''
                logger.debug(f"DEBUG: USD найден - parent: '{parent_text}', rate: '{rate_text}', результат: '{usd_rate}'")
            elif 'EUR' in parent_text:
                eur_match = re.search(r'\d+\.\d+', rate_text)
                eur_rate = eur_match.group(0) if eur_match else ''
                logger.debug(f"DEBUG: EUR найден - parent: '{parent_text}', rate: '{rate_text}', результат: '{eur_rate}'")
        
        logger.debug(f"DEBUG: Финальные курсы - USD: '{usd_rate}', EUR: '{eur_rate}'")
        
        return [
            {
                'id': 4029,
                'sectionId': 587,
                'name': 'EUR',
                'touroperator': 'Краски Мира',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4031,
                'sectionId': 587,
                'name': 'USD',
                'touroperator': 'Краски Мира',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_panteon_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Пантеона'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('div.b-courses.ajax-panel')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('div.b-courses.ajax-panel div div.b-courses__col.b-courses__col--3 span.b-courses__rub2')
        usd_element = soup.select_one('div.b-courses.ajax-panel div div.b-courses__col.b-courses__col--2 span.b-courses__rub1')
        eur_rate = eur_element.get_text().strip() if eur_element else ''
        usd_rate = usd_element.get_text().strip() if usd_element else ''
            
        return [
            {
                'id': 4197,
                'sectionId': 589,
                'name': 'EUR',
                'touroperator': 'Пантеон',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 4199,
                'sectionId': 589,
                'name': 'USD',
                'touroperator': 'Пантеон',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]
    
    def scrape_grand_travels_site(self, url: str) -> List[Dict]:
        '''Скрейпинг сайта Гранд-Экспресс'''
        soup = self.make_request(url)
        if not soup:
            return []

        # Попробуем несколько вариантов селекторов
        exchange_elements = [
            # Основной селектор для элемента с курсами
            soup.select_one('span.pbl'),
            soup.select_one('td.p span.pbl'),
            soup.select_one('.pbl'),
            # Альтернативные селекторы
            soup.select_one('table.t span.pbl'),
        ]
        
        exchange_element = None
        for elem in exchange_elements:
            if elem and elem.get_text(strip=True):
                exchange_element = elem
                break
        
        if not exchange_element:
            # Если не найден элемент, попробуем найти курсы по всему тексту страницы
            page_text = soup.get_text()
            logger.debug(f"DEBUG: Элемент с курсами не найден. Ищем по всему тексту страницы...")
            logger.debug(f"DEBUG: Фрагмент текста страницы: {page_text[:500]}...")
        else:
            page_text = exchange_element.get_text()
            logger.debug(f"DEBUG: Найден элемент с курсами: {page_text}")

        # Используем регулярные выражения для поиска курсов
        usd_match = re.search(r'1\s*USD\s*=\s*([\d.,]+)\s*руб', page_text, re.IGNORECASE)
        eur_match = re.search(r'1\s*EUR\s*=\s*([\d.,]+)\s*руб', page_text, re.IGNORECASE)
        
        logger.debug(f"DEBUG: USD match: {usd_match}")
        logger.debug(f"DEBUG: EUR match: {eur_match}")
        
        # Извлекаем курсы и конвертируем в float
        try:
            usd_rate = float(usd_match.group(1).replace(',', '.')) if usd_match else None
            eur_rate = float(eur_match.group(1).replace(',', '.')) if eur_match else None
        except (ValueError, AttributeError) as e:
            logger.debug(f"DEBUG: Ошибка конвертации курсов: {e}")
            usd_rate = None
            eur_rate = None
        
        logger.debug(f"DEBUG: USD rate: {usd_rate}, EUR rate: {eur_rate}")

        return [
            {
                'id': 17613,
                'sectionId': 667,
                'name': 'EUR',
                'touroperator': 'Гранд-Экспресс',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 17615,
                'sectionId': 667,
                'name': 'USD',
                'touroperator': 'Гранд-Экспресс',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_jettravel_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Джет Тревел'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('body > div.row.mx-1 > div > div > div:nth-child(1) > div.col-lg-7.col-12.mt-4 > div > div.b-currency__list')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('span:nth-child(1) > span.b-currency__num')
        usd_element = soup.select_one('span:nth-child(2) > span.b-currency__num')
        eur_rate = eur_element.get_text().strip() if eur_element else ''
        usd_rate = usd_element.get_text().strip() if usd_element else ''
            
        return [
            {
                'id': 19377,
                'sectionId': 677,
                'name': 'EUR',
                'touroperator': 'Джет Тревел',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 19375,
                'sectionId': 677,
                'name': 'USD',
                'touroperator': 'Джет Тревел',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_ambotis_site(self, url: str) -> List[Dict]:
        '''Скреппинг сайта Амботиса'''
        soup = self.make_request(url)
        if not soup:
            return []
        
        exchange_block = soup.select_one('body > div.page > footer > div > div > div:nth-child(3) > div > div:nth-child(1)')
        if not exchange_block:
            return []
        
        eur_element = soup.select_one('div > div > ul > li:nth-child(2) > span.currency__value.currency__value')
        usd_element = soup.select_one('div > div > ul > li:nth-child(1) > span.currency__value.currency__value')
        eur_rate = eur_element.get_text().strip() if eur_element else ''
        usd_rate = usd_element.get_text().strip() if usd_element else ''
            
        return [
            {
                'id': 3987,
                'sectionId': 567,
                'name': 'EUR',
                'touroperator': 'Амботис',
                'rate': eur_rate,
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 3989,
                'sectionId': 567,
                'name': 'USD',
                'touroperator': 'Амботис',
                'rate': usd_rate,
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_clickvoyage_site(self, url: str) -> List[Dict]:
        '''Скрейпинг сайта ClickVoyage'''
        soup = self.make_request(url)
        if not soup:
            return []

        currency_items = soup.select('.header-currency .header-currency-item')
        rates = {}

        for item in currency_items:
            text = item.get_text(strip=True)
            match = re.search(r'(EUR|USD)\s+([\d.]+)', text)
            if match:
                currency, rate = match.group(1), float(match.group(2))
                rates[currency] = rate

        return [
            {
                'id': 24381,
                'sectionId': 681,
                'name': 'EUR',
                'touroperator': 'Клик Вояж',
                'rate': rates.get('EUR'),
                'percentToCb': '',
                'delta': ''
            },
            {
                'id': 24379,
                'sectionId': 681,
                'name': 'USD',
                'touroperator': 'Клик Вояж',
                'rate': rates.get('USD'),
                'percentToCb': '',
                'delta': ''
            }
        ]

    def scrape_all_sites(self) -> Dict:
        '''Скреппинг всех сайтов'''
        sites_config = [
            # Полный список сайтов с их конфигурацией
            {
                'name': 'Tour_Kassa',
                'url': 'https://tour-kassa.ru/%D0%BA%D1%83%D1%80%D1%81%D1%8B-%D0%B2%D0%B0%D0%BB%D1%8E%D1%82-%D1%82%D1%83%D1%80%D0%BE%D0%BF%D0%B5%D1%80%D0%B0%D1%82%D0%BE%D1%80%D0%BE%D0%B2',
                'scraper': self.scrape_tour_kassa_site
            },
            {
                'name': 'ПАКС',
                'url': 'https://paks.ru/',  
                'scraper': self.scrape_paks_site
            },
            {
                'name': 'ПАК', 
                'url': 'https://www.pac.ru/',  
                'scraper': self.scrape_pak_site
            },
            {
                'name': 'АртТур', 
                'url': 'https://www.arttour.ru/',  
                'scraper': self.scrape_arttour_site
            },
            {
                'name': 'ICS', 
                'url': 'https://www.icstrvl.ru/index.html',  
                'scraper': self.scrape_icstrvl_site
            },
            {
                'name': 'Клик Вояж', 
                'url': 'https://clickvoyage.ru/',  
                'scraper': self.scrape_clickvoyage_site
            },
            {
                'name': 'Ambotis', 
                'url': 'https://www.ambotis.ru/',  
                'scraper': self.scrape_ambotis_site
            },
            {
                'name': 'Jet Travel', 
                'url': 'https://www.jettravel.ru/',  
                'scraper': self.scrape_jettravel_site
            },
            {
                'name': 'Grand Travels', 
                'url': 'https://grand-travels.ru/',  
                'scraper': self.scrape_grand_travels_site
            },
            {
                'name': 'Пантеон', 
                'url': 'https://www.panteon.ru/',  
                'scraper': self.scrape_panteon_site
            },
            {
                'name': 'CruClub', 
                'url': 'https://www.cruclub.ru/agent/howto/book/#pay',  
                'scraper': self.scrape_cruclub_site
            },
            {
                'name': 'Спектрум', 
                'url': 'https://spectrum.ru/turagentam/',  
                'scraper': self.scrape_spectrum_site
            },
            {
                'name': 'Туртранс', 
                'url': 'https://www.tourtrans.ru/',  
                'scraper': self.scrape_tourtrans_site
            },
            {
                'name': 'BSI', 
                'url': 'https://www.bsigroup.ru/',  
                'scraper': self.scrape_bsigroup_site
            },
            {
                'name': 'Квинта', 
                'url': 'https://www.quinta.ru/',  
                'scraper': self.scrape_quinta_site
            },
            {
                'name': 'Амиго Турс', 
                'url': 'https://www.amigo-tours.ru/',  
                'scraper': self.scrape_amigo_tours_site
            },
            {
                'name': 'Ванд', 
                'url': 'https://vand.ru/',  
                'scraper': self.scrape_vand_site
            },
            {
                'name': 'Space Travel', 
                'url': 'https://www.space-travel.ru/',  
                'scraper': self.scrape_space_travel_site
            }
        ]
        
        total_sites = len(sites_config)
        successful_sites = 0
        
        for site_config in sites_config:
            try:
                logger.info(f"Обрабатываю сайт: {site_config['name']}")
                site_results = site_config['scraper'](site_config['url'])
                self.results.extend(site_results)
                successful_sites += 1
                logger.info(f"Успешно обработан сайт {site_config['name']}: {len(site_results)} записей")
                
            except Exception as e:
                error_msg = f"Ошибка при обработке сайта {site_config['name']}: {str(e)}"
                logger.error(error_msg)
                self.errors.append(error_msg)
        
        return {
            'data': self.results,
            'summary': {
                'total_sites': total_sites,
                'successful_sites': successful_sites,
                'failed_sites': total_sites - successful_sites,
                'total_records': len(self.results),
                'errors': self.errors
            }
        }

class EmailNotifier:
    '''Класс для отправки email уведомлений'''
    
    def __init__(self, smtp_server: str, smtp_port: int, email: str, password: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email = email
        self.password = password

    def send_notification(self, subject: str, body: str, to_email: str):
        '''Отправка email уведомления'''
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email, self.password)
            text = msg.as_string()
            server.sendmail(self.email, to_email, text)
            server.quit()
            
            logger.info(f"Email отправлен на {to_email}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки email: {str(e)}")

def send_results_to_api(data: Dict, api_url: str) -> bool:
    '''Отправка результатов в API'''
    try:
        # Получение данных из запроса
        body = data
        response_array = []
        
        # Логирование полученных данных
        logging.info(f"Получено {len(body.get('data', []))} записей")
        logging.info(f"Статистика: {body.get('summary', {})}")
        logging.info(f"Данные JSON: {body.get('data', {})}")

        for touroperator_data in body.get('data', {}):
            сurrency_id = touroperator_data['id']

            rate = touroperator_data['rate']

            cb = touroperator_data['percentToCb']
            delta = touroperator_data['delta']

            params = {
                'TEMPLATE_ID': 617,
                'DOCUMENT_ID': ['lists', 'Bitrix\\Lists\\BizprocDocumentLists', сurrency_id],
                'PARAMETERS': {
                    'rate': rate,
                    'cb': cb,
                    'delta': delta
                }
            }

            try:
                response = requests.post(api_url, json=params, timeout=120)
                response.raise_for_status()
            except Exception as e:
                response_array.append({'error': str(e)})

        if (response_array != []):
            logger.info(f"Данные отправлены в API c ошибками: {response_array}")
            return False
        else:
            logger.info('Данные успешно отправлены в API')
            return True
    
    except Exception as e:
        logger.error(f"Ошибка отправки в API: {str(e)}")
        return False

def main():
    """Основная функция-обработчик для Yandex Cloud Functions"""
    
    # Получение переменных окружения
    outlook_email = os.getenv('OUTLOOK_EMAIL')
    outlook_password = os.getenv('OUTLOOK_PASSWORD')
    target_email = os.getenv('TARGET_EMAIL', 'andrey.koldayev@r-express.ru')
    api_url = os.getenv('API_URL')
    
    if not all([outlook_email, outlook_password, api_url]):
        error_msg = "Не все необходимые переменные окружения установлены"
        logger.error(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': error_msg})
        }
    
    # Явно указываем, что api_url теперь точно str, а не None
    api_url_str: str = str(api_url)
    
    start_time = datetime.now()
    
    try:
        # Инициализация скреппера
        scraper = CurrencyScraper()
        
        # Выполнение скреппинга
        logger.info("Начинаю скреппинг курсов валют")
        results = scraper.scrape_all_sites()
        
        # Отправка результатов в API
        api_success = send_results_to_api(results, api_url_str)
        
        # Подготовка отчета
        summary = results['summary']
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Инициализация email notifier
        if outlook_email is None or outlook_password is None:
            raise ValueError("outlook_email and outlook_password environment variables must be set and not None")
        # Явно приводим тип outlook_email к str, так как выше уже проверили на None
        notifier = EmailNotifier(
            smtp_server='smtp-mail.outlook.com',
            smtp_port=587,
            email=str(outlook_email),
            password=str(outlook_password) if outlook_password is not None else ""
        )
        
        # Отправка уведомления при ошибках или всегда (в зависимости от настроек)
        if summary['failed_sites'] > 0 or summary['errors'].__len__() > 0 or not api_success:
            subject = f"⚠️ Ошибки при скреппинге курсов валют - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            body = f"""
            <html>
            <body>
            <h2>Отчет о скреппинге курсов валют</h2>
            <p><strong>Время выполнения:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Длительность:</strong> {execution_time:.2f} секунд</p>
            
            <h3>Статистика:</h3>
            <ul>
                <li>Всего сайтов: {summary['total_sites']}</li>
                <li>Успешно обработано: {summary['successful_sites']}</li>
                <li>С ошибками: {summary['failed_sites']}</li>
                <li>Всего записей: {summary['total_records']}</li>
                <li>Отправка в API: {'✅ Успешно' if api_success else '❌ Ошибка'}</li>
            </ul>
            
            {f"<h3>Ошибки:</h3><ul>{''.join([f'<li>{error}</li>' for error in summary['errors']])}</ul>" if summary['errors'] else ""}
            </body>
            </html>
            """
            
            notifier.send_notification(subject, body, target_email)
        
        logger.info("Завершено успешно")
        
    except Exception as e:
        error_msg = f"Критическая ошибка: {str(e)}"
        logger.error(error_msg)
        
        # Отправка уведомления о критической ошибке
        try:
            notifier = EmailNotifier(
                smtp_server='smtp-mail.outlook.com',
                smtp_port=587,
                email=str(outlook_email),
                password=str(outlook_password) if outlook_password is not None else ""
            )
            
            subject = f"🚨 Критическая ошибка скреппинга - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            body = f"""<html><body><h2>Критическая ошибка</h2><p>{error_msg}</p><p>Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p></body></html>"""
            
            notifier.send_notification(subject, body, target_email)
        except:
            pass  # Если не удается отправить email, просто логируем
            
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Критическая ошибка: {str(e)}", exc_info=True)
