"""HTTP API 集成测试（临时 SQLite 数据库）。"""

import os
import tempfile
import pathlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("PLANNER_DB", tmp.name)

    # 延迟导入，确保读到环境变量
    from app import db as db_mod
    from app.main import app

    import sqlite3
    init_conn = sqlite3.connect(tmp.name)
    init_conn.executescript(db_mod.SCHEMA)
    init_conn.commit()
    init_conn.close()

    with TestClient(app) as c:
        yield c
    pathlib.Path(tmp.name).unlink(missing_ok=True)


CATALOG = {
    "note": "测试目录",
    "courses": [
        {"code": "CS101", "name": "程序设计", "credits": 4, "spring": True, "fall": True},
        {"code": "MATH101", "name": "高数", "credits": 5, "spring": True, "fall": True},
        {"code": "CS202", "name": "数据结构", "credits": 4, "spring": True, "fall": True,
         "prereq_groups": [["CS101"], ["MATH101"]]},
        {"code": "CS305", "name": "操作系统", "credits": 4, "spring": False, "fall": True,
         "prereq_groups": [["CS202"]], "coreqs": ["CS305L"]},
        {"code": "CS305L", "name": "操作系统实验", "credits": 1, "spring": False, "fall": True,
         "coreqs": ["CS305"]},
    ],
}


def _make_catalog(client, catalog=CATALOG):
    r = client.post("/api/catalogs", json=catalog)
    assert r.status_code == 201, r.text
    return r.json()["catalog_version"]["id"]


def _plan_body(**overrides):
    body = {
        "completed_courses": [],
        "target_courses": ["CS305"],
        "start_semester": {"year": 2026, "season": "fall"},
        "credit_cap": 10,
        "planning_terms": 6,
    }
    body.update(overrides)
    return body


def test_health_and_index(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 200


def test_full_workflow_create_plan_get_confirm(client):
    cid = _make_catalog(client)
    r = client.post("/api/plans", json=_plan_body())
    assert r.status_code == 201, r.text
    plan = r.json()["plan"]
    pid = plan["id"]
    assert plan["catalog_id"] == cid
    assert plan["status"] == "draft"
    semesters = [[c["code"] for c in s["courses"]] for s in plan["result"]["semesters"]]
    assert ["CS101", "MATH101"] in semesters
    assert ["CS305", "CS305L"] in semesters

    # 回看
    r2 = client.get(f"/api/plans/{pid}")
    assert r2.status_code == 200
    assert r2.json()["plan"]["result"] == plan["result"]

    # 确认
    r3 = client.post(f"/api/plans/{pid}/confirm")
    assert r3.status_code == 200
    assert r3.json()["plan"]["status"] == "confirmed"
    assert r3.json()["plan"]["confirmed_at"]

    # 重复确认 -> 409
    r4 = client.post(f"/api/plans/{pid}/confirm")
    assert r4.status_code == 409
    assert r4.json()["error"]["code"] == "already_confirmed"


def test_confirm_rejected_after_catalog_revision(client):
    cid1 = _make_catalog(client)
    r = client.post("/api/plans", json=_plan_body())
    pid = r.json()["plan"]["id"]
    assert r.json()["plan"]["catalog_id"] == cid1

    # 目录修订：发布新版本
    revised = {**CATALOG, "note": "测试目录 v2", "courses": [
        dict(c, credits=(c["credits"] + 1 if c["code"] == "CS202" else c["credits"]))
        for c in CATALOG["courses"]
    ]}
    cid2 = _make_catalog(client, revised)
    assert cid2 == cid1 + 1

    # 旧方案确认被拒
    r = client.post(f"/api/plans/{pid}/confirm")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "catalog_changed"
    assert err["details"]["bound_catalog_id"] == cid1
    assert err["details"]["latest_catalog_id"] == cid2
    # 确认未写入
    assert client.get(f"/api/plans/{pid}").json()["plan"]["status"] == "draft"

    # 方案绑定的旧目录版本仍可回看
    r = client.get(f"/api/catalogs/{cid1}")
    assert r.status_code == 200
    cs202_v1 = [c for c in r.json()["catalog_version"]["courses"] if c["code"] == "CS202"][0]
    assert cs202_v1["credits"] == 4


def test_plan_binds_specific_catalog_version(client):
    cid1 = _make_catalog(client)
    _make_catalog(client, {**CATALOG, "note": "v2", "courses": [
        dict(c) for c in CATALOG["courses"]
    ] + [{"code": "NEW1", "name": "新课", "credits": 2, "spring": True, "fall": True}]})
    # 显式绑定旧版本
    r = client.post("/api/plans?catalog_id=1", json=_plan_body())
    assert r.status_code == 201
    assert r.json()["plan"]["catalog_id"] == cid1
    # 绑定不存在版本 -> 404
    r = client.post("/api/plans?catalog_id=99", json=_plan_body())
    assert r.status_code == 404


def test_missing_target_course_404_no_plan_written(client):
    _make_catalog(client)
    r = client.post("/api/plans", json=_plan_body(target_courses=["NOPE"]))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "course_not_found"


def test_conflict_coreq_over_cap_409(client):
    cid = _make_catalog(client)
    body = _plan_body(target_courses=["CS305"], credit_cap=4)
    r = client.post("/api/plans", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_no_solution_422(client):
    _make_catalog(client)
    # 春起 3 学期：CS305 仅秋季 -> 只能落在第 2 学期(fall)，CS202 需更早(term0 春)，
    # 但 CS202 的两门先修又必须早于 term0 —— 无解
    body = _plan_body(target_courses=["CS305"], planning_terms=3,
                      start_semester={"year": 2026, "season": "spring"})
    r = client.post("/api/plans", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "no_solution"


def test_invalid_inputs_rejected(client):
    _make_catalog(client)
    base = _plan_body()

    # 空目标
    r = client.post("/api/plans", json={**base, "target_courses": []})
    assert r.status_code == 422

    # 目标全是空白（清洗后为空，也必须拒绝）
    r = client.post("/api/plans", json={**base, "target_courses": ["", "   "]})
    assert r.status_code == 422

    # 学分上限非正
    r = client.post("/api/plans", json={**base, "credit_cap": 0})
    assert r.status_code == 422
    r = client.post("/api/plans", json={**base, "credit_cap": -3})
    assert r.status_code == 422

    # 学期数非正
    r = client.post("/api/plans", json={**base, "planning_terms": 0})
    assert r.status_code == 422

    # 非法季节
    r = client.post("/api/plans", json={**base, "start_semester": {"year": 2026, "season": "winter"}})
    assert r.status_code == 422


def test_plan_when_no_catalog_409(client):
    r = client.post("/api/plans", json=_plan_body())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "catalog_not_found"


def test_catalog_referential_integrity(client):
    bad = {
        "note": "bad",
        "courses": [{"code": "A", "credits": 3, "spring": True, "fall": True,
                     "prereq_groups": [["GHOST"]]}],
    }
    r = client.post("/api/catalogs", json=bad)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "course_not_found"
    # 失败不留版本
    assert client.get("/api/catalogs").json()["catalog_versions"] == []


def test_invalid_catalog_course_no_season(client):
    bad = {"note": "bad", "courses": [{"code": "A", "credits": 3, "spring": False, "fall": False}]}
    r = client.post("/api/catalogs", json=bad)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_catalog"


def test_completed_target_empty_schedule(client):
    _make_catalog(client)
    body = _plan_body(completed_courses=["CS101", "MATH101", "CS202", "CS305", "CS305L"])
    r = client.post("/api/plans", json=body)
    assert r.status_code == 201
    result = r.json()["plan"]["result"]
    assert result["completed_already"] is True
    assert result["semesters"] == []


def test_catalog_list_and_latest(client):
    assert client.get("/api/catalogs/latest").status_code == 404
    cid = _make_catalog(client)
    r = client.get("/api/catalogs/latest")
    assert r.status_code == 200
    assert r.json()["catalog_version"]["id"] == cid
    assert len(r.json()["catalog_version"]["courses"]) == 5
    versions = client.get("/api/catalogs").json()["catalog_versions"]
    assert [v["id"] for v in versions] == [cid]


def test_plan_not_found(client):
    assert client.get("/api/plans/4242").status_code == 404


def test_seed_initialization():
    from app.init_db import init_db
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["PLANNER_DB"] = tmp.name
    init_db()
    init_db()  # 幂等
    import sqlite3
    conn = sqlite3.connect(tmp.name)
    n = conn.execute("SELECT COUNT(*) FROM catalog_versions").fetchone()[0]
    nc = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    conn.close()
    pathlib.Path(tmp.name).unlink(missing_ok=True)
    assert n == 1
    assert nc == 9
