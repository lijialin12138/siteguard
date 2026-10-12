"""SQLite 数据访问层。

先用 SQLite 跑通，等原型稳定后再迁移到华为云 RDS。
所有 SQL 都集中在这里，迁移时只需要改这一个文件。
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    url         TEXT    NOT NULL UNIQUE,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    status_code     INTEGER,
    response_ms     INTEGER,
    is_ok           INTEGER NOT NULL DEFAULT 0,
    ssl_days_left   INTEGER,
    title           TEXT,
    broken_links    INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    raw_json        TEXT,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL,
    level       TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (scan_id) REFERENCES scans (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL,
    model       TEXT,
    result_json TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (scan_id) REFERENCES scans (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scans_site ON scans (site_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_issues_scan ON issues (scan_id);
CREATE INDEX IF NOT EXISTS idx_diag_scan ON diagnoses (scan_id, id DESC);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    """建库建表。每次启动调用一次，幂等。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """获取连接。自动提交 / 回滚，并把查询结果转成 dict。"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_to_dicts(rows: Any) -> list[dict]:
    return [dict(r) for r in rows]
