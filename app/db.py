"""SQLite 数据库连接与表结构。"""

from __future__ import annotations

import os
import sqlite3

DEFAULT_DB_PATH = "/data/planner.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    course_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS courses (
    catalog_id  INTEGER NOT NULL REFERENCES catalog_versions(id) ON DELETE CASCADE,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    credits     INTEGER NOT NULL,
    season_spring INTEGER NOT NULL,
    season_fall   INTEGER NOT NULL,
    PRIMARY KEY (catalog_id, code)
);

CREATE TABLE IF NOT EXISTS course_prereq_groups (
    catalog_id  INTEGER NOT NULL REFERENCES catalog_versions(id) ON DELETE CASCADE,
    course_code TEXT NOT NULL,
    group_index INTEGER NOT NULL,
    member_code TEXT NOT NULL,
    PRIMARY KEY (catalog_id, course_code, group_index, member_code)
);

CREATE TABLE IF NOT EXISTS course_coreqs (
    catalog_id  INTEGER NOT NULL REFERENCES catalog_versions(id) ON DELETE CASCADE,
    course_code TEXT NOT NULL,
    coreq_code  TEXT NOT NULL,
    PRIMARY KEY (catalog_id, course_code, coreq_code)
);

CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id  INTEGER NOT NULL REFERENCES catalog_versions(id),
    status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    request_json TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    confirmed_at TEXT
);
"""


def get_db_path() -> str:
    # 每次调用都读环境变量，便于测试在导入后切换数据库
    return os.environ.get("PLANNER_DB", DEFAULT_DB_PATH)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
