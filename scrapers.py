"""Scrapers públicos de LinkedIn Jobs, Indeed y Computrabajo."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

from playwright.async_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

LOGGER = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
]


class BaseJobScraper(ABC):
    """Comportamiento común: navegación, pausas y extracción tolerante."""

    source_name = "unknown"

    def __init__(
        self,
        browser: Browser,
        delay_seconds: float = 2.0,
        max_jobs: int = 20,
    ) -> None:
        self.browser = browser
        self.delay_seconds = delay_seconds
        self.max_jobs = max_jobs
        # Una sola navegación simultánea por fuente reduce timeouts y evita
        # generar un patrón agresivo contra el sitio.
        self._request_lock = asyncio.Semaphore(1)

    @abstractmethod
    def build_url(self, keyword: str, location: str) -> str:
        """Construye la URL pública de la primera página."""

    @abstractmethod
    async def extract_jobs(self, page: Page) -> list[dict[str, str]]:
        """Extrae tarjetas de la página actual."""

    async def scrape(self, keyword: str, location: str) -> list[dict[str, str]]:
        async with self._request_lock:
            context = await self.browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="es-CO",
                extra_http_headers={"Accept-Language": "es-CO,es;q=0.9"},
            )
            # Las tarjetas no dependen de imágenes, fuentes ni vídeo. Evitar
            # esos recursos hace la navegación más estable, no cambia el DOM.
            async def handle_route(route: Any) -> None:
                if route.request.resource_type in {"image", "font", "media"}:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", handle_route)
            page = await context.new_page()
            url = self.build_url(keyword, location)
            self.requested_location = location
            try:
                response = await page.goto(
                    url,
                    # "commit" no espera recursos secundarios que pueden quedar
                    # pendientes; después esperamos el DOM por separado.
                    wait_until="commit",
                    timeout=30_000,
                )
                try:
                    await page.wait_for_load_state(
                        "domcontentloaded", timeout=20_000
                    )
                except PlaywrightTimeoutError:
                    LOGGER.warning(
                        "%s no terminó domcontentloaded; se intentará extraer "
                        "el DOM parcial (%s)",
                        self.source_name,
                        url,
                    )
                status = response.status if response else "sin respuesta"
                LOGGER.info("%s respondió HTTP %s: %s", self.source_name, status, url)
                await asyncio.sleep(self.delay_seconds + random.uniform(0, 1))
                extraction_started = time.perf_counter()
                jobs = await self.extract_jobs(page)
                LOGGER.info(
                    "%s extrajo %d ofertas en %.2f segundos",
                    self.source_name,
                    len(jobs),
                    time.perf_counter() - extraction_started,
                )
                return jobs
            except PlaywrightTimeoutError as exc:
                LOGGER.warning("%s agotó el tiempo navegando a %s: %s", self.source_name, url, exc)
                return []
            except Exception as exc:
                LOGGER.warning("%s falló navegando a %s: %s", self.source_name, url, exc)
                return []
            finally:
                await context.close()

    @staticmethod
    async def first_text(card: Any, selectors: tuple[str, ...], default: str) -> str:
        """Prueba selectores alternativos para sobrevivir cambios del DOM."""
        for selector in selectors:
            try:
                value = (
                    await card.locator(selector).first.inner_text(timeout=1_500)
                ).strip()
                if value:
                    return value
            except Exception:
                continue
        return default

    @staticmethod
    async def first_link(
        card: Any,
        selectors: tuple[str, ...],
        base_url: str,
        preserve_query: bool = False,
    ) -> str:
        for selector in selectors:
            try:
                href = await card.locator(selector).first.get_attribute(
                    "href", timeout=1_500
                )
                if href:
                    resolved = urljoin(base_url, href)
                    return resolved if preserve_query else resolved.split("?")[0]
            except Exception:
                continue
        return ""

    @staticmethod
    def infer_modality(text: str) -> str:
        lowered = text.lower()
        if re.search(r"\b(remot[oa]|remote|teletrabajo)\b", lowered):
            return "Remoto"
        if re.search(r"\b(h[ií]brid[oa]|hybrid)\b", lowered):
            return "Híbrido"
        if re.search(r"\b(presencial|on[- ]?site)\b", lowered):
            return "Presencial"
        return "No especificada"

    @staticmethod
    def location_matches(location: str, allowed_locations: list[str]) -> bool:
        """Comprueba ubicación real sin confundir ciudades con otros países."""
        def normalize(value: str) -> str:
            decomposed = unicodedata.normalize("NFKD", value.lower())
            return "".join(
                char for char in decomposed
                if not unicodedata.combining(char)
            )

        actual = normalize(location)
        if not actual or actual == "ubicacion no especificada":
            return False
        for allowed in allowed_locations:
            expected = normalize(allowed)
            if expected == "remoto":
                if re.search(r"\b(remoto|remote|teletrabajo)\b", actual):
                    return True
            elif re.search(rf"\b{re.escape(expected)}\b", actual):
                return True
        return False


class LinkedInScraper(BaseJobScraper):
    source_name = "LinkedIn"

    def build_url(self, keyword: str, location: str) -> str:
        return (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(keyword)}&location={quote_plus(location)}"
        )

    async def extract_jobs(self, page: Page) -> list[dict[str, str]]:
        # Estos selectores corresponden a tarjetas públicas; si LinkedIn cambia
        # sus clases, actualizar primero CARD_SELECTORS y luego los campos.
        cards = page.locator("li.jobs-search__results-list > div, "
                             "ul.jobs-search__results-list > li")
        return await self._extract_cards(page, cards)

    async def _extract_cards(self, page: Page, cards: Any) -> list[dict[str, str]]:
        jobs = []
        card_count = await cards.count()
        LOGGER.info("%s encontró %d tarjetas candidatas", self.source_name, card_count)
        for index in range(min(card_count, self.max_jobs)):
            card = cards.nth(index)
            title = await self.first_text(card, (".base-search-card__title", "h3"), "")
            if not title:
                continue
            company = await self.first_text(card, (".base-search-card__subtitle", "h4"), "")
            location = await self.first_text(card, (".job-search-card__location", ".job-search-card__location"), "")
            link = await self.first_link(card, (".base-card__full-link", "a"), page.url)
            jobs.append({"title": title, "company": company, "location": location,
                         "modality": self.infer_modality(f"{title} {location}"), "link": link})
        return jobs


class IndeedScraper(BaseJobScraper):
    source_name = "Indeed"

    def build_url(self, keyword: str, location: str) -> str:
        return f"https://co.indeed.com/jobs?q={quote_plus(keyword)}&l={quote_plus(location)}"

    async def extract_jobs(self, page: Page) -> list[dict[str, str]]:
        cards = page.locator("div.job_seen_beacon, div.cardOutline, td.result")
        jobs = []
        card_count = await cards.count()
        LOGGER.info("%s encontró %d tarjetas candidatas", self.source_name, card_count)
        for index in range(min(card_count, self.max_jobs)):
            card = cards.nth(index)
            title = await self.first_text(
                card,
                (
                    "h2.jobTitle span",
                    "h2.jobTitle",
                    "a.jcs-JobTitle",
                    "h2 a",
                    "[data-testid='job-title']",
                ),
                "",
            )
            if not title:
                title = await self.first_text(
                    card,
                    ("a[data-jk]", "a.jcs-JobTitle"),
                    "",
                )
            if not title:
                continue
            company = await self.first_text(
                card,
                (
                    "[data-testid='company-name']",
                    "[data-testid='companyName']",
                    ".companyName",
                ),
                "Empresa no especificada",
            )
            location = await self.first_text(
                card,
                (
                    "[data-testid='text-location']",
                    "[data-testid='job-location']",
                    ".companyLocation",
                ),
                "",
            )
            link = await self.first_link(
                card,
                ("a.jcs-JobTitle", "h2 a", "a[data-jk]"),
                page.url,
                preserve_query=True,
            )
            if link:
                parsed_link = urlparse(link)
                if (
                    "indeed." not in parsed_link.netloc
                    or not parse_qs(parsed_link.query).get("jk")
                ):
                    LOGGER.warning("Enlace de Indeed inválido descartado: %s", link)
                    link = ""
            jobs.append({"title": title, "company": company, "location": location,
                         "modality": self.infer_modality(f"{title} {location}"), "link": link})
        return jobs


class ComputrabajoScraper(BaseJobScraper):
    source_name = "Computrabajo"

    def build_url(self, keyword: str, location: str) -> str:
        keyword_slug = quote_plus(keyword).replace("+", "-")
        location_slug = quote_plus(location).replace("+", "-")
        return (
            "https://co.computrabajo.com/trabajo-de-"
            f"{keyword_slug}-en-{location_slug}"
        )

    async def extract_jobs(self, page: Page) -> list[dict[str, str]]:
        # Computrabajo usa article.box_offer en varias versiones; se conserva
        # un fallback por si la página sirve una variante del marcado.
        cards = page.locator("article.box_offer, .box_offer, .js-o-link")
        jobs = []
        card_count = await cards.count()
        LOGGER.info("%s encontró %d tarjetas candidatas", self.source_name, card_count)
        for index in range(min(card_count, self.max_jobs)):
            card = cards.nth(index)
            title = await self.first_text(card, ("h2", ".js-o-link", "a.js-o-link"), "")
            if not title:
                continue
            company = await self.first_text(card, (".fc_base", ".fs16", "[class*='company']"), "")
            location = await self.first_text(
                card,
                (
                    ".breadcrumb li:last-child",
                    ".breadcrumb",
                    ".listado-ubicacion",
                    ".mr10",
                    "[class*='location']",
                ),
                "",
            )
            link = await self.first_link(card, ("a.js-o-link", "h2 a", "a"), page.url)
            jobs.append({"title": title, "company": company, "location": location,
                         "modality": self.infer_modality(f"{title} {location}"), "link": link})
        return jobs
