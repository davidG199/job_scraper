"""Persistencia local de ofertas y control de duplicados."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class JobDatabase:
    """Repositorio SQLite para ofertas encontradas por los scrapers."""

    def __init__(self, database_path: str | Path = "jobs.sqlite3") -> None:
        self.database_path = str(database_path)
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        """Crea la tabla e índices de forma idempotente."""
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id_hash TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    link TEXT NOT NULL,
                    date_extracted TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"
            )

    @staticmethod
    def make_job_hash(job: dict[str, str]) -> str:
        """Genera una clave estable; la URL es el identificador preferido."""
        identity = job.get("link", "").strip() or "|".join(
            job.get(field, "").strip().lower()
            for field in ("title", "company", "location")
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def insert_if_new(self, job: dict[str, str]) -> bool:
        """Inserta una oferta y devuelve True solo cuando era nueva."""
        job_id_hash = self.make_job_hash(job)
        extracted_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO jobs
                    (job_id_hash, title, company, location, modality, link,
                     date_extracted, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'new')
                """,
                (
                    job_id_hash,
                    job.get("title", "Sin título"),
                    job.get("company", "Empresa no especificada"),
                    job.get("location", "Ubicación no especificada"),
                    job.get("modality", "No especificada"),
                    job.get("link", ""),
                    extracted_at,
                ),
            )
            return cursor.rowcount == 1

    def update_status(self, job: dict[str, str], status: str) -> None:
        """Actualiza el estado de una oferta ya persistida."""
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET status = ? WHERE job_id_hash = ?",
                (status, self.make_job_hash(job)),
            )

    def get_pending_jobs(self) -> list[dict[str, str]]:
        """Devuelve ofertas guardadas que aún no fueron notificadas."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT title, company, location, modality, link
                FROM jobs
                WHERE status = 'new'
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]
