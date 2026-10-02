#!/usr/bin/env bash
# 高校课程学期规划服务 —— HTTP API 调用示例（curl）
#
# 用法：
#   1. 先启动服务：docker compose up --build
#   2. 另开终端执行：bash examples/api_examples.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
j() { python3 -m json.tool 2>/dev/null || cat; }

echo "============================================================"
echo "0. 健康检查"
echo "============================================================"
curl -sS "$BASE/health"; echo

echo "============================================================"
echo "1. 查看最新目录版本（容器初始化时已写入示例目录）"
echo "============================================================"
curl -sS "$BASE/api/catalogs/latest" | j

echo "============================================================"
echo "2. 生成规划方案"
echo "    目标：CS305 操作系统；无已修课；2026 秋起；每学期上限 10 学分；8 学期"
echo "============================================================"
PLAN_JSON=$(curl -sS -X POST "$BASE/api/plans" \
  -H 'Content-Type: application/json' \
  -d '{
    "completed_courses": [],
    "target_courses": ["CS305"],
    "start_semester": {"year": 2026, "season": "fall"},
    "credit_cap": 10,
    "planning_terms": 8
  }')
echo "$PLAN_JSON" | j
PLAN_ID=$(echo "$PLAN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['plan']['id'])")
CATALOG_ID=$(echo "$PLAN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['plan']['catalog_id'])")

echo "============================================================"
echo "3. 回看方案（方案绑定目录版本 id=$CATALOG_ID）"
echo "============================================================"
curl -sS "$BASE/api/plans/$PLAN_ID" | j

echo "============================================================"
echo "4. 确认方案"
echo "============================================================"
curl -sS -X POST "$BASE/api/plans/$PLAN_ID/confirm" | j

echo "============================================================"
echo "5. 非法输入：credit_cap=0（预期 422，被拒绝）"
echo "============================================================"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$BASE/api/plans" \
  -H 'Content-Type: application/json' \
  -d '{
    "target_courses": ["CS305"],
    "start_semester": {"year": 2026, "season": "fall"},
    "credit_cap": 0,
    "planning_terms": 8
  }'

echo "============================================================"
echo "6. 课程缺失：目标课程不存在（预期 404 course_not_found，不返回课表）"
echo "============================================================"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$BASE/api/plans" \
  -H 'Content-Type: application/json' \
  -d '{
    "target_courses": ["CS999"],
    "start_semester": {"year": 2026, "season": "fall"},
    "credit_cap": 10,
    "planning_terms": 8
  }'

echo "============================================================"
echo "7. 无解：3 学期内完成 CS401 编译原理（预期 422 no_solution）"
echo "============================================================"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$BASE/api/plans" \
  -H 'Content-Type: application/json' \
  -d '{
    "target_courses": ["CS401"],
    "start_semester": {"year": 2026, "season": "fall"},
    "credit_cap": 10,
    "planning_terms": 3
  }'

echo
echo "示例执行完毕。交互式文档：$BASE/docs"
