"""Database connection helpers."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extras

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/equibles"


def get_db_url(override: str | None = None) -> str:
    if override:
        return override
    return os.environ.get("EQUIBLES_DB_URL", DEFAULT_DB_URL)


@contextmanager
def connect(db_url: str | None = None) -> Iterator[psycopg2.extensions.connection]:
    url = get_db_url(db_url)
    try:
        conn = psycopg2.connect(url, connect_timeout=5)
    except psycopg2.OperationalError as e:
        msg = str(e).strip()
        sys.stderr.write(
            "ERROR: Could not connect to Equibles database.\n"
            f"  URL: {_redact(url)}\n"
            f"  Detail: {msg}\n\n"
            "Hints:\n"
            "  - Is the stack running? `docker compose up -d` from the repo root.\n"
            "  - Is another Postgres on 5432? `lsof -nP -iTCP:5432 -sTCP:LISTEN`\n"
            "  - Override with EQUIBLES_DB_URL (e.g. against the container IP).\n"
        )
        sys.exit(2)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def cursor(db_url: str | None = None) -> Iterator[psycopg2.extras.RealDictCursor]:
    with connect(db_url) as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    try:
        scheme, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return url
    except ValueError:
        return url
