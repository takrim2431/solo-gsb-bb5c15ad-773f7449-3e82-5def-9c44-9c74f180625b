"""FastAPI 应用：课程目录版本管理与学期规划 HTTP API。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import repository as repo
from .db import connect
from .planner import PlanningError, build_plan
from .schemas import CatalogCreate, PlanCreate

app = FastAPI(
    title="高校课程学期规划服务",
    version="1.0.0",
    description=(
        "基于课程目录版本为学生生成期限内最早完成的学期规划。"
        "先修每组任选一门、各组均须满足且须在更早学期完成；"
        "未修的同修课必须同学期安排。"
    ),
)


@contextmanager
def db_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_conn():
    with db_conn() as conn:
        yield conn


# ---------------------------------------------------------------------------
# 统一错误响应
# ---------------------------------------------------------------------------

@app.exception_handler(PlanningError)
async def planning_error_handler(_: Request, exc: PlanningError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_input",
                "message": "请求参数非法，已拒绝（详见 details）。",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/", tags=["meta"])
def index() -> dict:
    return {
        "service": "高校课程学期规划服务",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "endpoints": {
            "创建目录版本": "POST /api/catalogs",
            "目录版本列表": "GET /api/catalogs",
            "最新目录版本": "GET /api/catalogs/latest",
            "目录版本详情": "GET /api/catalogs/{catalog_id}",
            "生成规划方案": "POST /api/plans",
            "查看方案(绑定目录版本)": "GET /api/plans/{plan_id}",
            "确认方案": "POST /api/plans/{plan_id}/confirm",
        },
    }


# ---------------------------------------------------------------------------
# 课程目录（版本化）
# ---------------------------------------------------------------------------

@app.post("/api/catalogs", status_code=201, tags=["catalogs"])
def create_catalog(payload: CatalogCreate, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """发布一个新的目录版本。每次修订都会产生新版本，旧版本保持不变。"""
    try:
        meta = repo.create_catalog_version(conn, payload)
    except Exception:
        conn.rollback()
        raise
    return {"catalog_version": meta}


@app.get("/api/catalogs", tags=["catalogs"])
def list_catalogs(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return {"catalog_versions": repo.list_catalog_versions(conn)}


@app.get("/api/catalogs/latest", tags=["catalogs"])
def latest_catalog(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    latest_id = repo.latest_catalog_id(conn)
    if latest_id is None:
        raise PlanningError(
            "catalog_not_found", "当前还没有任何课程目录版本。", http_status=404
        )
    return {"catalog_version": repo.catalog_detail(conn, latest_id)}


@app.get("/api/catalogs/{catalog_id}", tags=["catalogs"])
def get_catalog(catalog_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return {"catalog_version": repo.catalog_detail(conn, catalog_id)}


# ---------------------------------------------------------------------------
# 规划方案
# ---------------------------------------------------------------------------

@app.post("/api/plans", status_code=201, tags=["plans"])
def create_plan(
    payload: PlanCreate,
    catalog_id: int | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """生成规划方案并绑定一个目录版本。

    - 不传 ``catalog_id`` 时绑定最新目录版本；
    - 方案创建为 draft；目标缺失、条件冲突或无解时返回错误，不写入任何方案。
    """
    if catalog_id is None:
        catalog_id = repo.latest_catalog_id(conn)
        if catalog_id is None:
            raise PlanningError(
                "catalog_not_found",
                "当前还没有任何课程目录版本，无法规划。请先通过 POST /api/catalogs 创建。",
                http_status=409,
            )

    catalog = repo.load_catalog(conn, catalog_id)  # 版本不存在 -> 404

    start = payload.start_semester
    result = build_plan(
        catalog=catalog,
        completed=payload.completed_courses,
        targets=payload.target_courses,
        start_year=start.year,
        start_season=start.season,
        credit_cap=payload.credit_cap,
        planning_terms=payload.planning_terms,
    )

    request_obj = payload.model_dump()
    result_obj: dict[str, Any] = {"catalog_id": catalog_id, **result}
    plan_id = repo.insert_plan(conn, catalog_id, request_obj, result_obj)
    return {"plan": repo.get_plan(conn, plan_id)}


@app.get("/api/plans/{plan_id}", tags=["plans"])
def get_plan(plan_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """回看方案。响应包含其绑定的 catalog_id，可据此回看当时的目录版本。"""
    return {"plan": repo.get_plan(conn, plan_id)}


@app.post("/api/plans/{plan_id}/confirm", tags=["plans"])
def confirm_plan(plan_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """确认方案。若绑定目录之后又发布了新版本（目录已变化），拒绝确认且不写入。"""
    return {"plan": repo.confirm_plan(conn, plan_id)}
