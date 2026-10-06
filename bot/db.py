# -*- coding: utf-8 -*-
"""
Хранилище на SQLite. Простая синхронная обёртка — нагрузка (одна кофейня,
ручной ввод бариста) не требует асинхронной БД.
"""
import sqlite3
import secrets
import string
from contextlib import contextmanager
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from . import config

# Колонки, добавленные после первого релиза (миграция для уже существующей БД).
_MIGRATIONS = [
    ("valid_until", "TEXT"),                    # последний день действия, YYYY-MM-DD
    ("uses", "INTEGER NOT NULL DEFAULT 0"),     # сколько раз использован (для недельных призов)
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS spins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    redeem_code TEXT UNIQUE NOT NULL,
    prize_code TEXT NOT NULL,
    location TEXT NOT NULL,
    staff_tg_id INTEGER NOT NULL,
    staff_name TEXT,
    created_at TEXT NOT NULL,
    redeemed_at TEXT,
    redeemed_by_tg_id INTEGER,
    redeemed_by_name TEXT,
    note TEXT,
    valid_until TEXT,
    uses INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_spins_created_at ON spins(created_at);
CREATE INDEX IF NOT EXISTS idx_spins_redeem_code ON spins(redeem_code);
"""

_CODE_ALPHABET = string.ascii_uppercase + string.digits
# Excludes visually ambiguous chars (0/O, 1/I) to reduce mistakes when read aloud.
_CODE_ALPHABET = "".join(c for c in _CODE_ALPHABET if c not in "01OI")


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(spins)")}
        for name, decl in _MIGRATIONS:
            if name not in existing:
                conn.execute(f"ALTER TABLE spins ADD COLUMN {name} {decl}")


def now_local() -> datetime:
    """Текущее время по часовому поясу заведения (без tzinfo, как хранится в БД)."""
    tz = timezone(timedelta(hours=config.TZ_OFFSET_HOURS))
    return datetime.now(tz).replace(tzinfo=None)


def today_local() -> date:
    return now_local().date()


def _gen_redeem_code(conn, length: int = 6) -> str:
    while True:
        code = "JOJA-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
        exists = conn.execute(
            "SELECT 1 FROM spins WHERE redeem_code = ?", (code,)
        ).fetchone()
        if not exists:
            return code


def create_spin(
    prize_code: str,
    location: str,
    staff_tg_id: int,
    staff_name: Optional[str],
    valid_until: Optional[str] = None,
) -> dict:
    with get_conn() as conn:
        redeem_code = _gen_redeem_code(conn)
        now = now_local().isoformat(timespec="seconds")
        conn.execute(
            """INSERT INTO spins (redeem_code, prize_code, location, staff_tg_id,
                                   staff_name, created_at, valid_until)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (redeem_code, prize_code, location, staff_tg_id, staff_name, now, valid_until),
        )
        row = conn.execute(
            "SELECT * FROM spins WHERE redeem_code = ?", (redeem_code,)
        ).fetchone()
        return dict(row)


def find_spin(redeem_code: str) -> Optional[dict]:
    redeem_code = redeem_code.strip().upper()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM spins WHERE redeem_code = ?", (redeem_code,)
        ).fetchone()
        return dict(row) if row else None


def redeem_spin(redeem_code: str, redeemed_by_tg_id: int, redeemed_by_name: Optional[str]) -> Optional[dict]:
    redeem_code = redeem_code.strip().upper()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM spins WHERE redeem_code = ?", (redeem_code,)
        ).fetchone()
        if not row:
            return None
        if row["redeemed_at"]:
            return dict(row)  # already redeemed — caller checks redeemed_at
        now = now_local().isoformat(timespec="seconds")
        conn.execute(
            """UPDATE spins SET redeemed_at = ?, redeemed_by_tg_id = ?, redeemed_by_name = ?
               WHERE redeem_code = ?""",
            (now, redeemed_by_tg_id, redeemed_by_name, redeem_code),
        )
        row = conn.execute(
            "SELECT * FROM spins WHERE redeem_code = ?", (redeem_code,)
        ).fetchone()
        return dict(row)


def register_use(redeem_code: str) -> Optional[dict]:
    """Фиксирует очередное использование многоразового (недельного) приза.

    Код при этом НЕ закрывается (redeemed_at остаётся пустым) — приз действует
    до конца срока. Возвращает обновлённую строку со счётчиком uses.
    """
    redeem_code = redeem_code.strip().upper()
    with get_conn() as conn:
        conn.execute(
            "UPDATE spins SET uses = uses + 1 WHERE redeem_code = ?", (redeem_code,)
        )
        row = conn.execute(
            "SELECT * FROM spins WHERE redeem_code = ?", (redeem_code,)
        ).fetchone()
        return dict(row) if row else None


def daily_report(day: Optional[date] = None, location: Optional[str] = None) -> list[dict]:
    """Все спины за календарный день (по умолчанию — сегодня)."""
    if day is None:
        day = today_local()
    prefix = day.isoformat()  # 'YYYY-MM-DD'
    with get_conn() as conn:
        if location:
            rows = conn.execute(
                """SELECT * FROM spins WHERE created_at LIKE ? AND location = ?
                   ORDER BY created_at""",
                (prefix + "%", location),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM spins WHERE created_at LIKE ? ORDER BY created_at",
                (prefix + "%",),
            ).fetchall()
        return [dict(r) for r in rows]


def unredeemed_older_than(days: int = 0) -> list[dict]:
    """Список непогашенных призов (для контроля просроченных)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM spins WHERE redeemed_at IS NULL ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
