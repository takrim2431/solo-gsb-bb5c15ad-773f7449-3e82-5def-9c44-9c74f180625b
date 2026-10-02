# 目录修订示例：发布新版本后，旧方案确认会被拒绝（catalog_changed）
# 用法：bash examples/revision_example.sh
set -euo pipefail
BASE="${BASE:-http://localhost:8000}"

echo ">> 基于当前目录生成方案"
PLAN=$(curl -sS -X POST "$BASE/api/plans" -H 'Content-Type: application/json' -d '{
  "completed_courses": [],
  "target_courses": ["CS305"],
  "start_semester": {"year": 2026, "season": "fall"},
  "credit_cap": 10,
  "planning_terms": 8
}')
PLAN_ID=$(echo "$PLAN" | python3 -c "import json,sys; print(json.load(sys.stdin)['plan']['id'])")
echo "   plan_id=$PLAN_ID"

echo ">> 发布目录新版本（新增一门选修课 CS501，重复执行也幂等）"
curl -sS "$BASE/api/catalogs/latest" \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)["catalog_version"]
# 去掉可能已存在的 CS501，保证脚本可重复执行
courses = [{
    "code": c["code"], "name": c["name"], "credits": c["credits"],
    "spring": c["spring"], "fall": c["fall"],
    "prereq_groups": c["prereq_groups"], "coreqs": c["coreqs"],
} for c in d["courses"] if c["code"] != "CS501"]
courses.append({"code": "CS501", "name": "机器学习专题", "credits": 2,
                "spring": True, "fall": False, "prereq_groups": [["CS301"]]})
print(json.dumps({"note": "目录修订：新增 CS501", "courses": courses}, ensure_ascii=False))
' > /tmp/catalog_v2.json
curl -sS -X POST "$BASE/api/catalogs" -H 'Content-Type: application/json' \
  -d @/tmp/catalog_v2.json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["catalog_version"]; print("   新版本 id =", d["id"])'

echo ">> 尝试确认旧方案（目录已变化，预期 409 catalog_changed，且不写入）"
curl -sS -w '\n   HTTP %{http_code}\n' -X POST "$BASE/api/plans/$PLAN_ID/confirm"

echo ">> 基于最新目录重新规划后再确认"
NEW_PLAN=$(curl -sS -X POST "$BASE/api/plans" -H 'Content-Type: application/json' -d '{
  "completed_courses": [],
  "target_courses": ["CS305"],
  "start_semester": {"year": 2026, "season": "fall"},
  "credit_cap": 10,
  "planning_terms": 8
}')
NEW_ID=$(echo "$NEW_PLAN" | python3 -c "import json,sys; print(json.load(sys.stdin)['plan']['id'])")
curl -sS -X POST "$BASE/api/plans/$NEW_ID/confirm" \
  | python3 -c '
import json, sys
p = json.load(sys.stdin)["plan"]
print("   新方案", p["id"], "状态 =", p["status"])
'
