"""目录版本与规划方案的数据访问层。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .planner import Course, PlanningError, SPRING, FALL
from .schemas import CatalogCreate


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------

def create_catalog_version(conn: sqlite3.Connection, payload: CatalogCreate) -> dict:
    course_map = {c.code: c for c in payload.courses}

    # 引用完整性：同修 / 先修必须指向目录内存在的课程
    missing: list[str] = []
    for c in payload.courses:
        for q in c.coreqs:
            if q not in course_map:
                missing.append(f"{c.code}.coreqs -> {q}")
        for g in c.prereq_groups:
            for m in g:
                if m not in course_map:
                    missing.append(f"{c.code}.prereq_groups -> {m}")
    if missing:
        raise PlanningError(
            "course_not_found",
            "目录中存在指向未知课程的先修/同修引用。",
            http_status=422,
            details={"references": sorted(set(missing))},
        )

    # 所有课程至少在一个学期开课（先校验再写入，保证失败时不留半成品数据）
    no_season = [c.code for c in payload.courses if not (c.spring or c.fall)]
    if no_season:
        raise PlanningError(
            "invalid_catalog",
            f"课程至少需要在一个学期开课（spring/fall 不能同时为 false）：{', '.join(sorted(no_season))}",
            http_status=422,
            details={"courses": sorted(no_season)},
        )

    cur = conn.execute("INSERT INTO catalog_versions (note, course_count) VALUES (?, 0)", (payload.note,))
    catalog_id = cur.lastrowid

    for c in payload.courses:
        conn.execute(
            "INSERT INTO courses (catalog_id, code, name, credits, season_spring, season_fall)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (catalog_id, c.code, c.name, c.credits, int(c.spring), int(c.fall)),
        )
        for gi, g in enumerate(c.prereq_groups):
            for m in g:
                conn.execute(
                    "INSERT INTO course_prereq_groups (catalog_id, course_code, group_index, member_code)"
                    " VALUES (?, ?, ?, ?)",
                    (catalog_id, c.code, gi, m),
                )
        for q in c.coreqs:
            conn.execute(
                "INSERT INTO course_coreqs (catalog_id, course_code, coreq_code) VALUES (?, ?, ?)",
                (catalog_id, c.code, q),
            )

    conn.execute(
        "UPDATE catalog_versions SET course_count = ? WHERE id = ?",
        (len(payload.courses), catalog_id),
    )
    conn.commit()
    return get_catalog_meta(conn, catalog_id)


def get_catalog_meta(conn: sqlite3.Connection, catalog_id: int) -> dict:
    row = conn.execute(
        "SELECT id, note, created_at, course_count FROM catalog_versions WHERE id = ?",
        (catalog_id,),
    ).fetchone()
    if row is None:
        raise PlanningError(
            "catalog_not_found",
            f"目录版本 {catalog_id} 不存在。",
            http_status=404,
            details={"catalog_id": catalog_id},
        )
    return {"id": row[0], "note": row[1], "created_at": row[2], "course_count": row[3]}


def latest_catalog_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(id) AS m FROM catalog_versions").fetchone()
    return row["m"] if row and row["m"] is not None else None


def list_catalog_versions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, note, created_at, course_count FROM catalog_versions ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def load_catalog(conn: sqlite3.Connection, catalog_id: int) -> dict[str, Course]:
    get_catalog_meta(conn, catalog_id)  # 不存在则 404
    rows = conn.execute(
        "SELECT code, name, credits, season_spring, season_fall"
        " FROM courses WHERE catalog_id = ? ORDER BY code",
        (catalog_id,),
    ).fetchall()

    groups: dict[str, list[set[str]]] = {}
    for r in conn.execute(
        "SELECT course_code, group_index, member_code FROM course_prereq_groups"
        " WHERE catalog_id = ? ORDER BY course_code, group_index, member_code",
        (catalog_id,),
    ):
        groups.setdefault(r["course_code"], {}).setdefault(r["group_index"], set()).add(r["member_code"])

    coreqs: dict[str, set[str]] = {}
    for r in conn.execute(
        "SELECT course_code, coreq_code FROM course_coreqs WHERE catalog_id = ?",
        (catalog_id,),
    ):
        coreqs.setdefault(r["course_code"], set()).add(r["coreq_code"])

    catalog: dict[str, Course] = {}
    for r in rows:
        code = r["code"]
        seasons = frozenset(
            s for s, flag in ((SPRING, r["season_spring"]), (FALL, r["season_fall"])) if flag
        )
        catalog[code] = Course(
            code=code,
            name=r["name"],
            credits=r["credits"],
            seasons=seasons,
            prereq_groups=tuple(frozenset(g) for g in (groups.get(code, {}).values())),
            coreqs=frozenset(coreqs.get(code, set())),
        )
    return catalog


def catalog_detail(conn: sqlite3.Connection, catalog_id: int) -> dict[str, Any]:
    meta = get_catalog_meta(conn, catalog_id)
    catalog = load_catalog(conn, catalog_id)
    courses = []
    for code in sorted(catalog):
        c = catalog[code]
        courses.append(
            {
                "code": c.code,
                "name": c.name,
                "credits": c.credits,
                "spring": SPRING in c.seasons,
                "fall": FALL in c.seasons,
                "prereq_groups": [sorted(g) for g in c.prereq_groups],
                "coreqs": sorted(c.coreqs),
            }
        )
    return {**meta, "courses": courses}


# ---------------------------------------------------------------------------
# 规划方案
# ---------------------------------------------------------------------------

def insert_plan(
    conn: sqlite3.Connection,
    catalog_id: int,
    request_obj: dict,
    result_obj: dict,
) -> int:
    cur = conn.execute(
        "INSERT INTO plans (catalog_id, status, request_json, result_json)"
        " VALUES (?, 'draft', ?, ?)",
        (catalog_id, json.dumps(request_obj, ensure_ascii=False), json.dumps(result_obj, ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def _row_to_plan(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "catalog_id": row["catalog_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"],
        "request": json.loads(row["request_json"]),
        "result": json.loads(row["result_json"]),
    }


def get_plan(conn: sqlite3.Connection, plan_id: int) -> dict:
    row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        raise PlanningError(
            "plan_not_found",
            f"方案 {plan_id} 不存在。",
            http_status=404,
            details={"plan_id": plan_id},
        )
    return _row_to_plan(row)


def confirm_plan(conn: sqlite3.Connection, plan_id: int) -> dict:
    plan = get_plan(conn, plan_id)
    if plan["status"] == "confirmed":
        raise PlanningError(
            "already_confirmed",
            f"方案 {plan_id} 已确认，无需重复确认。",
            http_status=409,
            details={"plan_id": plan_id, "confirmed_at": plan["confirmed_at"]},
        )

    # 乐观并发：仅当绑定目录仍是最新版本时允许确认。
    # 用条件 UPDATE 原子完成“检查 + 写入”，消除检查与更新之间的竞态；
    # 目录已修订则 0 行受影响，拒绝确认且不写入。
    cur = conn.execute(
        "UPDATE plans"
        " SET status = 'confirmed', confirmed_at = datetime('now')"
        " WHERE id = ?"
        "   AND status = 'draft'"
        "   AND catalog_id = (SELECT MAX(id) FROM catalog_versions)",
        (plan_id,),
    )
    conn.commit()
    if cur.rowcount == 0:
        current_latest = latest_catalog_id(conn)
        if current_latest != plan["catalog_id"]:
            raise PlanningError(
                "catalog_changed",
                "目录已发布新版本，本方案绑定的目录已过期，拒绝确认且未写入任何确认记录。"
                "请基于最新目录重新规划。",
                http_status=409,
                details={
                    "plan_id": plan_id,
                    "bound_catalog_id": plan["catalog_id"],
                    "latest_catalog_id": current_latest,
                },
            )
        raise PlanningError(
            "already_confirmed",
            f"方案 {plan_id} 已确认，无需重复确认。",
            http_status=409,
            details={"plan_id": plan_id},
        )
    return get_plan(conn, plan_id)
