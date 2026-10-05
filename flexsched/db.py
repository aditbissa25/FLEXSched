"""SQLite connection handling and schema initialisation.

sqlite3 ships with Python - no server to install. The whole database is a
single file (``data/flexsched.db``), or ``:memory:`` for tests.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from . import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1

# One consistent text format for datetimes. ISO-8601 strings sort correctly
# as plain text, so ORDER BY / comparisons work without conversion.
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def to_db_time(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.strftime(DATETIME_FMT)


def from_db_time(value: Optional[str]) -> Optional[datetime]:
    return None if value is None else datetime.strptime(value, DATETIME_FMT)


def connect(path: Union[str, Path, None] = None) -> sqlite3.Connection:
    """Open (and if needed create) the database, returning a ready connection."""
    target = str(path if path is not None else config.DB_PATH)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row             # rows behave like dicts: row["title"]
    conn.execute("PRAGMA foreign_keys = ON")   # SQLite has FKs OFF by default!
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if missing and record the schema version."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < SCHEMA_VERSION:
        # Future migrations would go here: "if current < 2: ALTER TABLE ...".
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
