"""数据库初始化：建表并写入示例目录（数据已存在时幂等跳过）。

用法：python -m app.init_db
"""

from __future__ import annotations

import os
import sqlite3

from .db import SCHEMA, get_db_path
from .schemas import CatalogCreate
from . import repository as repo

SEED = CatalogCreate(
    note="示例目录 v1：计算机专业核心课程",
    courses=[
        {
            "code": "CS101",
            "name": "程序设计基础",
            "credits": 4,
            "spring": True,
            "fall": True,
            "prereq_groups": [],
            "coreqs": [],
        },
        {
            "code": "MATH101",
            "name": "高等数学",
            "credits": 5,
            "spring": True,
            "fall": True,
            "prereq_groups": [],
            "coreqs": [],
        },
        {
            "code": "MATH201",
            "name": "离散数学",
            "credits": 3,
            "spring": True,
            "fall": False,
            "prereq_groups": [["MATH101"]],
            "coreqs": [],
        },
        {
            "code": "PHYS101",
            "name": "大学物理",
            "credits": 4,
            "spring": True,
            "fall": False,
            "prereq_groups": [["MATH101"]],
            "coreqs": [],
        },
        {
            "code": "CS202",
            "name": "数据结构",
            "credits": 4,
            "spring": True,
            "fall": True,
            "prereq_groups": [["CS101"], ["MATH101"]],
            "coreqs": [],
        },
        {
            "code": "CS301",
            "name": "算法设计",
            "credits": 3,
            "spring": True,
            "fall": True,
            # 任选一组：离散数学 或 大学物理（演示“每组任选一门”）
            "prereq_groups": [["MATH201", "PHYS101"], ["CS202"]],
            "coreqs": [],
        },
        {
            "code": "CS305",
            "name": "操作系统",
            "credits": 4,
            "spring": False,
            "fall": True,
            "prereq_groups": [["CS301"], ["CS202"]],
            "coreqs": ["CS305L"],
        },
        {
            "code": "CS305L",
            "name": "操作系统实验",
            "credits": 1,
            "spring": False,
            "fall": True,
            "prereq_groups": [],
            "coreqs": ["CS305"],
        },
        {
            "code": "CS401",
            "name": "编译原理",
            "credits": 4,
            "spring": True,
            "fall": False,
            "prereq_groups": [["CS301"]],
            "coreqs": [],
        },
    ],
)


def init_db() -> None:
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        count = conn.execute("SELECT COUNT(*) AS c FROM catalog_versions").fetchone()[0]
        if count == 0:
            meta = repo.create_catalog_version(conn, SEED)
            print(f"已写入示例目录版本：id={meta['id']}，课程数={meta['course_count']}")
        else:
            print(f"数据库已存在 {count} 个目录版本，跳过示例数据写入。")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"数据库初始化完成：{get_db_path()}")
