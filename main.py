"""Punto de entrada de Job Scraper V1.0."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from database import JobDatabase
from scrapers import ComputrabajoScraper, IndeedScraper, LinkedInScraper
from telegram_notifier import (
    TelegramRateLimitError,
    send_job_notification,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

# Carga el archivo .env situado junto a este módulo. Los valores no se
# escriben en config.json ni se incluyen en los mensajes de log.
load_dotenv(Path(__file__).with_name(".env"))


def load_config(path: Path = Path("config.json")) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


async def main() -> None:
    config = load_config()
    database = JobDatabase(config.get("database_path", "jobs.sqlite3"))
    telegram = config["telegram"]
    keywords = config.get("keywords", [])
    locations = config.get("locations", [])
    max_keywords = config.get("max_keywords")
    max_locations = config.get("max_locations")
    for name, value in (
        ("max_keywords", max_keywords),
        ("max_locations", max_locations),
    ):
        if value is not None and (not isinstance(value, int) or value < 1):
            raise ValueError(f"{name} debe ser un entero positivo o null.")

    selected_keywords = (
        keywords[:max_keywords] if max_keywords is not None else keywords
    )
    selected_locations = (
        locations[:max_locations] if max_locations is not None else locations
    )
    max_jobs = config.get("max_jobs_per_query", 20)
    if not isinstance(max_jobs, int) or max_jobs < 1:
        raise ValueError("max_jobs_per_query debe ser un entero positivo.")
    notification_delay = config.get("notification_delay_seconds", 4.0)
    max_telegram_retries = config.get("telegram_max_retries", 3)
    if not isinstance(notification_delay, (int, float)) or notification_delay < 0:
        raise ValueError("notification_delay_seconds debe ser >= 0.")
    if not isinstance(max_telegram_retries, int) or max_telegram_retries < 0:
        raise ValueError("telegram_max_retries debe ser un entero >= 0.")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=bool(config.get("headless", True))
        )
        scrapers = (
            LinkedInScraper(
                browser, config.get("request_delay_seconds", 2.0), max_jobs
            ),
            IndeedScraper(
                browser, config.get("request_delay_seconds", 2.0), max_jobs
            ),
            ComputrabajoScraper(
                browser, config.get("request_delay_seconds", 2.0), max_jobs
            ),
        )
        try:
            # Cada combinación permite ampliar la cobertura sin acoplar los
            # scrapers al formato del archivo de configuración.
            query_pairs = [
                (keyword, location)
                for keyword in selected_keywords
                for location in selected_locations
            ]
            tasks = [
                scraper.scrape(keyword, location)
                for scraper in scrapers
                for keyword, location in query_pairs
            ]
            LOGGER.info(
                "Ejecutando %d consultas por fuente: %d keywords x %d "
                "ubicaciones (%d fuentes).",
                len(query_pairs),
                len(selected_keywords),
                len(selected_locations),
                len(scrapers),
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)
            scraped_jobs = [
                job
                for result in results
                if isinstance(result, list)
                for job in result
            ]
            jobs = []
            rejected_by_location = 0
            for job in scraped_jobs:
                if any(
                    scraper.location_matches(
                        job.get("location", ""), selected_locations
                    )
                    for scraper in scrapers
                ):
                    jobs.append(job)
                else:
                    rejected_by_location += 1
            LOGGER.info(
                "Ofertas extraídas: %d; rechazadas por ubicación: %d",
                len(jobs),
                rejected_by_location,
            )
            for job in jobs:
                database.insert_if_new(job)

            # También reintenta ofertas de ejecuciones anteriores que fueron
            # guardadas, pero cuyo envío a Telegram falló.
            pending_jobs = [
                job
                for job in database.get_pending_jobs()
                if any(
                    scraper.location_matches(
                        job.get("location", ""), selected_locations
                    )
                    for scraper in scrapers
                )
            ]
            LOGGER.info("Ofertas pendientes de notificar: %d", len(pending_jobs))
            for job in pending_jobs:
                for attempt in range(max_telegram_retries + 1):
                    try:
                        await send_job_notification(
                            job,
                            telegram["bot_token"],
                            str(telegram["chat_id"]),
                        )
                        database.update_status(job, "notified")
                        LOGGER.info("Oferta notificada: %s", job["title"])
                        await asyncio.sleep(notification_delay)
                        break
                    except TelegramRateLimitError as exc:
                        if attempt >= max_telegram_retries:
                            LOGGER.error(
                                "Se agotaron los reintentos de Telegram para %s",
                                job.get("link"),
                            )
                            break
                        wait_seconds = exc.retry_after + 1
                        LOGGER.warning(
                            "Telegram limitó el envío; reintentando en %d "
                            "segundos (%d/%d)",
                            wait_seconds,
                            attempt + 1,
                            max_telegram_retries,
                        )
                        await asyncio.sleep(wait_seconds)
                    except Exception:
                        # Se conserva status='new' para reintentar en otro ciclo.
                        LOGGER.exception("No se pudo notificar %s", job.get("link"))
                        break
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
