"""Envío de alertas de ofertas a Telegram."""

from __future__ import annotations

import html
import os
from urllib.parse import urlparse
from typing import Mapping

import httpx


class TelegramRateLimitError(RuntimeError):
    """Indica que Telegram pidió esperar antes de reintentar."""

    def __init__(self, retry_after: int, description: str) -> None:
        super().__init__(description)
        self.retry_after = max(retry_after, 1)


def _configured_value(value: str) -> str:
    """Permite usar valores literales o referencias ${ENV_VAR} en config.json."""
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


async def send_job_notification(
    job: Mapping[str, str],
    bot_token: str,
    chat_id: str,
    timeout_seconds: float = 20.0,
) -> None:
    """Envía una oferta usando el endpoint oficial sendMessage de Telegram."""
    token = _configured_value(bot_token)
    destination = _configured_value(chat_id)
    if not token or not destination:
        raise ValueError(
            "Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en el entorno."
        )

    link = job.get("link", "").strip()
    parsed_link = urlparse(link)
    if parsed_link.scheme not in {"http", "https"}:
        link = ""

    # Se deja el enlace como texto plano. Así una URL malformada no puede
    # invalidar toda la entidad HTML del mensaje de Telegram.
    message = (
        f"<b>{html.escape(job.get('title', 'Sin título'))}</b>\n"
        f"Empresa: {html.escape(job.get('company', 'No especificada'))}\n"
        f"Ubicación: {html.escape(job.get('location', 'No especificada'))}\n"
        f"Modalidad: {html.escape(job.get('modality', 'No especificada'))}"
    )
    if link:
        message += f"\nVer oferta: {html.escape(link)}"
    if len(message) > 4096:
        message = message[:4080] + "\n…"
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            endpoint,
            data={
                "chat_id": destination,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "false",
            },
        )
        payload = response.json()
        if response.status_code == 429:
            retry_after = payload.get("parameters", {}).get("retry_after", 1)
            raise TelegramRateLimitError(
                int(retry_after),
                payload.get("description", "Telegram rate limit exceeded"),
            )
        if response.is_error or not payload.get("ok"):
            description = payload.get("description", response.text)
            raise RuntimeError(
                f"Telegram rechazó el mensaje (HTTP {response.status_code}): "
                f"{description}"
            )
