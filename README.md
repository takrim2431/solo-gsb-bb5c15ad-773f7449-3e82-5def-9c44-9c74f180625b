# 高校课程学期规划服务

基于 **Python + FastAPI + SQLite** 的课程学期规划服务。学生提供已修课程、目标课程、
起始学期、每学期学分上限与规划学期数，服务返回**期限内最早完成的完整课表**。

## 功能与规则

- 课程目录记录：学分、春/秋开课学期、先修条件、同修课程。
- **先修条件**：每个先修组内"任选一门"即可，但**所有组都必须满足**；先修课必须安排在
  **更早的学期**（不能同学期修读）。
- **同修课程**：若学生尚未修过，必须与该课程安排在**同一学期**；已修过的同修课不再排入。
- 已修课程不会重复排入；方案只包含**目标课程及满足其条件所必需的课程**，不含冗余课。
- 每学期总学分不得超过上限；课程只能排在其开课的春/秋季。
- 方案优选：① 完成学期最早；② 完成学期相同时，按"各学期课程代码序列"的字典序取最小
  （空学期序列 `()` 排在最前；空学期会被保留，因此课表与实际学期严格对应）。
- 课程缺失、条件冲突（先修成环、同修组学分超限/无共同开课季）或期限内无解时，
  **返回错误原因，绝不返回部分课表**。
- 目录的每次修订都会生成**不可变的新版本**；方案创建时**绑定目录版本**，可随时回看
  当时的目录与方案。
- **确认方案**时若目录已发布更新版本，则拒绝确认（`409 catalog_changed`）且不写入确认记录。
- 非法输入（空目标、学分/学期数上限非正、非法季节等）一律拒绝（`422 invalid_input`）。

## 目录结构

```
.
├── app/
│   ├── main.py         # FastAPI 应用与 HTTP 路由
│   ├── planner.py      # 规划引擎（纯函数，含冲突/无解检测与回溯搜索）
│   ├── repository.py   # 目录版本与方案的数据访问层
│   ├── db.py           # SQLite 连接与建表语句
│   ├── schemas.py      # Pydantic 输入模型与校验
│   └── init_db.py      # 数据库初始化 + 示例目录
├── examples/           # curl / Python 调用示例
├── tests/              # 引擎与 API 测试（39 个用例）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 一键启动（Docker Compose，推荐）

需要 Docker 20.10+ 与 Docker Compose v2：

```bash
docker compose up --build
```

容器启动时会自动：

1. 在持久化卷 `planner-data`（容器内 `/data/planner.db`）初始化 SQLite 数据库、建表；
2. 首次启动写入一份 9 门课的示例目录（之后重启幂等跳过）；
3. 启动 uvicorn 服务。

访问地址与端口（默认映射到宿主机 **8000**）：

| 用途 | 地址 |
| --- | --- |
| 服务根（接口清单） | http://localhost:8000/ |
| 健康检查 | http://localhost:8000/health |
| Swagger 交互式文档 | http://localhost:8000/docs |
| OpenAPI 描述 | http://localhost:8000/openapi.json |

停止 / 清理：

```bash
docker compose down            # 停止并删除容器（数据保留在卷中）
docker compose down -v         # 同时删除数据卷（清空数据库）
```

### 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PLANNER_DB` | `/data/planner.db` | SQLite 数据库文件路径 |
| 宿主机端口 | `8000` | 修改 `docker-compose.yml` 中 `ports`，如 `"8080:8000"` |

如需更换数据库文件位置，可在 `docker-compose.yml` 中把卷挂载改为本地目录：

```yaml
volumes:
  - ./data:/data
```

## 本地非 Docker 运行（开发）

需要 Python 3.11：

```bash
pip install -r requirements.txt
export PLANNER_DB=/tmp/planner.db          # 可选，默认 /data/planner.db
python -m app.init_db                      # 初始化数据库 + 示例目录
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
python -m pytest tests/ -q
```

## HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/catalogs` | 发布一个新的**目录版本**（修订即新版本，旧版本保留） |
| GET | `/api/catalogs` | 目录版本列表 |
| GET | `/api/catalogs/latest` | 最新目录版本详情 |
| GET | `/api/catalogs/{catalog_id}` | 指定目录版本详情（供回看） |
| POST | `/api/plans?catalog_id=` | 生成规划方案；不传 `catalog_id` 时绑定最新版本 |
| GET | `/api/plans/{plan_id}` | 回看方案（含绑定的 `catalog_id`、请求参数与完整课表） |
| POST | `/api/plans/{plan_id}/confirm` | 确认方案；目录已变化则拒绝且不写入 |

错误响应统一为：

```json
{"error": {"code": "no_solution", "message": "…说明原因…", "details": {}}}
```

| 错误码 | HTTP | 含义 |
| --- | --- | --- |
| `invalid_input` | 422 | 请求参数非法（空目标、上限非正、非法季节等） |
| `course_not_found` | 404/422 | 目标课程缺失；或目录中存在指向未知课程的引用 |
| `conflict` | 409 | 条件冲突：先修成环、单课学分超限、同修组学分超限/无共同开课季 |
| `no_solution` | 422 | 期限内无解（窗口/学分不足等），不返回任何课表 |
| `catalog_not_found` | 404/409 | 指定目录版本不存在，或尚无任何目录 |
| `catalog_changed` | 409 | 确认时目录已修订，方案过期，拒绝确认 |
| `already_confirmed` | 409 | 方案已确认，不能重复确认 |

### 1）创建目录版本

```bash
curl -X POST http://localhost:8000/api/catalogs \
  -H 'Content-Type: application/json' \
  -d '{
    "note": "2026 培养方案",
    "courses": [
      {"code": "CS101", "name": "程序设计基础", "credits": 4,
       "spring": true, "fall": true, "prereq_groups": [], "coreqs": []},
      {"code": "MATH101", "name": "高等数学", "credits": 5,
       "spring": true, "fall": true},
      {"code": "MATH201", "name": "离散数学", "credits": 3,
       "spring": true, "fall": false, "prereq_groups": [["MATH101"]]},
      {"code": "PHYS101", "name": "大学物理", "credits": 4,
       "spring": true, "fall": false, "prereq_groups": [["MATH101"]]},
      {"code": "CS202", "name": "数据结构", "credits": 4,
       "spring": true, "fall": true,
       "prereq_groups": [["CS101"], ["MATH101"]],
       "coreqs": []},
      {"code": "CS301", "name": "算法设计", "credits": 3,
       "spring": true, "fall": true,
       "prereq_groups": [["MATH201", "PHYS101"], ["CS202"]]},
      {"code": "CS305", "name": "操作系统", "credits": 4,
       "spring": false, "fall": true,
       "prereq_groups": [["CS301"], ["CS202"]],
       "coreqs": ["CS305L"]},
      {"code": "CS305L", "name": "操作系统实验", "credits": 1,
       "spring": false, "fall": true, "coreqs": ["CS305"]}
    ]
  }'
```

字段说明：

- `prereq_groups`：先修组的列表；每个内层列表是**一组**，组内课程任选一门，
  多组之间是"与"关系。例：`[["MATH201","PHYS101"], ["CS202"]]` 表示
  （MATH201 或 PHYS101 任选一门）**且**（已修 CS202）。
- `coreqs`：同修课程；双方都应声明（如 CS305 与 CS305L）。
- `spring`/`fall`：开课学期，至少一个为 `true`。

### 2）生成规划方案

```bash
curl -X POST http://localhost:8000/api/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "completed_courses": [],
    "target_courses": ["CS305"],
    "start_semester": {"year": 2026, "season": "fall"},
    "credit_cap": 10,
    "planning_terms": 8
  }'
```

校验规则：`target_courses` 必须非空；`credit_cap`、`planning_terms` 必须为正整数；
`season` 只能是 `spring`/`fall`。任一不满足返回 422。

响应（节选，完整示例见 `examples/`）：

```json
{
  "plan": {
    "id": 1,
    "catalog_id": 1,
    "status": "draft",
    "request": { "...": "原始请求参数" },
    "result": {
      "start_semester": {"index": 1, "year": 2026, "season": "fall"},
      "completion_semester": {"index": 5, "year": 2028, "season": "fall"},
      "semesters": [
        {"index": 1, "year": 2026, "season": "fall",
         "courses": [{"code": "CS101", "name": "程序设计基础", "credits": 4},
                     {"code": "MATH101", "name": "高等数学", "credits": 5}],
         "total_credits": 9},
        {"index": 2, "year": 2027, "season": "spring",
         "courses": [{"code": "CS202", "...": "..."},
                     {"code": "MATH201", "...": "..."}],
         "total_credits": 7},
        {"index": 3, "year": 2027, "season": "fall", "courses": [], "total_credits": 0},
        {"index": 4, "year": 2028, "season": "spring",
         "courses": [{"code": "CS301", "...": "..."}], "total_credits": 3},
        {"index": 5, "year": 2028, "season": "fall",
         "courses": [{"code": "CS305", "...": "..."},
                     {"code": "CS305L", "...": "..."}], "total_credits": 5}
      ]
    }
  }
}
```

若目标课程都已修过，返回 `completed_already: true` 且 `semesters: []`。

### 3）回看方案与绑定目录

```bash
curl http://localhost:8000/api/plans/1          # 方案（含 catalog_id）
curl http://localhost:8000/api/catalogs/1       # 方案绑定的那版目录
```

### 4）确认方案（目录变更保护）

```bash
curl -X POST http://localhost:8000/api/plans/1/confirm
```

确认时服务检查方案绑定的目录是否仍为最新版本：

- 是最新版本 → 状态变为 `confirmed`，记录 `confirmed_at`；
- 之后又发布过新版本 → 返回 `409 catalog_changed`，**不写入任何确认记录**，
  需用最新目录重新 `POST /api/plans`。

## 调用示例

服务启动后执行：

```bash
bash examples/api_examples.sh         # 覆盖成功与各类失败场景（curl）
python3 examples/api_examples.py      # 同上，仅用 Python 标准库
bash examples/revision_example.sh     # 目录修订 → 旧方案确认被拒 → 重新规划确认
```

## 实现说明（规划引擎）

1. **必修课闭包**：从目标课沿"未修同修课"和"单成员先修组"展开；多成员先修组的课程只是
   候选项。
2. **固有冲突检测**：必修课先修依赖图成环、单课学分超限、同修连通组学分超上限或无共同
   开课季 → 直接返回 `conflict`。
3. **回溯搜索**：先放置全部目标课（同修课以连通闭包整体落同一学期），再逐个满足尚未
   覆盖的先修组（每个候选课程 × 每个更早学期分支）；状态记忆化去重。
4. **叶节点裁剪**：只保留能通过"目标 ← 先修/同修支撑链"证明为必需的课程，杜绝冗余课。
5. **最优选择**：以 `(完成学期, 各学期课程代码有序元组)` 的全序比较取最小解，即"最早完成，
   字典序最小"。
