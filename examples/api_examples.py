#!/usr/bin/env python3
"""高校课程学期规划服务 —— HTTP API 调用示例（仅依赖 Python 标准库）。

运行前请先启动服务：docker compose up --build
然后执行：python3 examples/api_examples.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://localhost:8000")


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def show(title: str, status: int, payload: dict) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(f"HTTP {status}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    status, payload = call("GET", "/health")
    show("0. 健康检查", status, payload)

    status, payload = call("GET", "/api/catalogs/latest")
    show("1. 最新目录版本", status, payload)

    plan_request = {
        "completed_courses": [],
        "target_courses": ["CS305"],
        "start_semester": {"year": 2026, "season": "fall"},
        "credit_cap": 10,
        "planning_terms": 8,
    }
    status, payload = call("POST", "/api/plans", plan_request)
    show("2. 生成规划方案（目标 CS305，2026 秋起）", status, payload)

    if status == 201:
        plan = payload["plan"]
        plan_id = plan["id"]

        status, payload = call("GET", f"/api/plans/{plan_id}")
        show(f"3. 回看方案（绑定目录版本 catalog_id={plan['catalog_id']}）", status, payload)

        status, payload = call("POST", f"/api/plans/{plan_id}/confirm")
        show("4. 确认方案", status, payload)

    # ---- 错误场景 ----
    status, payload = call(
        "POST",
        "/api/plans",
        {
            "target_courses": ["CS305"],
            "start_semester": {"year": 2026, "season": "fall"},
            "credit_cap": 0,  # 必须为正
            "planning_terms": 8,
        },
    )
    show("5. 非法输入（credit_cap=0，应被拒绝）", status, payload)

    status, payload = call(
        "POST",
        "/api/plans",
        {
            "target_courses": ["CS999"],
            "start_semester": {"year": 2026, "season": "fall"},
            "credit_cap": 10,
            "planning_terms": 8,
        },
    )
    show("6. 课程缺失（course_not_found，不返回课表）", status, payload)

    status, payload = call(
        "POST",
        "/api/plans",
        {
            "target_courses": ["CS401"],
            "start_semester": {"year": 2026, "season": "fall"},
            "credit_cap": 10,
            "planning_terms": 3,
        },
    )
    show("7. 期限内无解（no_solution，不返回部分课表）", status, payload)


if __name__ == "__main__":
    main()
