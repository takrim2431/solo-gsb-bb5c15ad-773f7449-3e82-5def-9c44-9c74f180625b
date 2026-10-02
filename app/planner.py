"""高校课程学期规划引擎（纯函数，不涉及数据库与 HTTP，便于单元测试）。

规则要点：
- 先修条件分为若干组，每组“任选一门”即可，但所有组都必须满足；
- 先修课必须安排在 *更早* 的学期（不能同学期）；
- 同修课若学生尚未修过，必须与该课安排在 *同一* 学期；
- 已修课程不再排入，方案中只保留目标课及满足其条件所必需的课程；
- 在规划学期数内返回最早完成的完整方案；完成学期相同时，
  按“各学期课程代码序列”的字典序取最小者；空学期序列排在最前。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

SPRING = "spring"
FALL = "fall"
SEASONS = (SPRING, FALL)

# 搜索节点上限，避免极端输入下搜索时间无限膨胀
_NODE_LIMIT = 200_000


class PlanningError(Exception):
    """规划业务异常，携带错误码、HTTP 状态码与明细。"""

    def __init__(self, code: str, message: str, http_status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


@dataclass(frozen=True)
class Course:
    code: str
    name: str
    credits: int
    seasons: frozenset[str]
    prereq_groups: tuple[frozenset[str], ...]
    coreqs: frozenset[str]


def other_season(season: str) -> str:
    return FALL if season == SPRING else SPRING


def term_label(start_year: int, start_season: str, index: int) -> tuple[int, str]:
    """index 为从起始学期开始的 0 基学期序号，返回 (学年, 春秋季)。"""
    elapsed_years = (index + (1 if start_season == FALL else 0)) // 2
    season = start_season if index % 2 == 0 else other_season(start_season)
    return start_year + elapsed_years, season


def _semester_dict(index: int, year: int, season: str) -> dict:
    return {"index": index, "year": year, "season": season}


def build_plan(
    catalog: dict[str, Course],
    completed: list[str] | set[str],
    targets: list[str] | set[str],
    start_year: int,
    start_season: str,
    credit_cap: int,
    planning_terms: int,
) -> dict:
    """计算学期规划方案。失败时抛出 PlanningError，绝不返回部分课表。"""

    completed = {c for c in completed}
    targets = {c for c in targets}

    # 目录中缺失、且未声称已修的目标课程 -> 课程缺失
    missing = sorted(c for c in targets if c not in catalog and c not in completed)
    if missing:
        raise PlanningError(
            "course_not_found",
            f"目标课程在当前目录中缺失：{', '.join(missing)}",
            http_status=404,
            details={"missing_courses": missing},
        )

    # 已修但目录中不存在的课程（校外学分/旧版课程）视为幻影已修课，
    # 仅用于满足先修条件，不参与排课与学分计算。
    need = {c for c in targets if c not in completed}

    start_semester = _semester_dict(1, start_year, start_season)
    if not need:
        return {
            "completed_already": True,
            "start_semester": start_semester,
            "completion_semester": None,
            "semesters": [],
            "message": "所有目标课程均已修过，无需再排课。",
        }

    n_terms = planning_terms

    def season_at(i: int) -> str:
        return start_season if i % 2 == 0 else other_season(start_season)

    # ------------------------------------------------------------------
    # 1) 求“必修课”集合：目标课 + 未修同修课 + 只有一个可选成员的先修组。
    #    多成员先修组的课程只是候选项，不纳入固有冲突检测。
    # ------------------------------------------------------------------
    mandatory: set[str] = set()
    stack = list(need)
    while stack:
        c = stack.pop()
        if c in mandatory or c in completed:
            continue
        mandatory.add(c)
        for q in catalog[c].coreqs:
            if q not in completed and q not in mandatory:
                stack.append(q)
        for g in catalog[c].prereq_groups:
            if any(m in completed for m in g):
                continue
            if len(g) == 1:
                m = next(iter(g))
                if m not in completed and m not in mandatory:
                    stack.append(m)

    # ------------------------------------------------------------------
    # 2) 固有冲突检测（与学期窗口无关，任何期限下都不可能完成）
    # ------------------------------------------------------------------

    # 2.1 单门必修课学分超过每学期上限
    over_cap = sorted(c for c in mandatory if catalog[c].credits > credit_cap)
    if over_cap:
        raise PlanningError(
            "conflict",
            f"课程学分超过每学期学分上限，无法安排：{', '.join(over_cap)}",
            http_status=409,
            details={"courses": over_cap, "credit_cap": credit_cap},
        )

    # 2.2 必修课之间“硬性”先修依赖有向图存在回路 -> 先修无法在更早学期完成。
    #     只有组内 *未修成员恰为一门* 的先修组构成不可选择的硬边；多成员组
    #     存在替代课，可能打破回路，不纳入结构检测（此类极端情形由后续穷尽
    #     搜索精确判定无解，避免误报冲突）。
    edges: dict[str, list[str]] = {}
    for c in mandatory:
        ms: set[str] = set()
        for g in catalog[c].prereq_groups:
            open_members = [m for m in g if m not in completed]
            if len(open_members) == 1 and open_members[0] in mandatory:
                ms.add(open_members[0])
        edges[c] = sorted(ms)

    color: dict[str, int] = {}
    path: list[str] = []

    def find_cycle(u: str) -> list[str] | None:
        color[u] = 1
        path.append(u)
        for v in edges[u]:
            if color.get(v) == 1:
                i = path.index(v)
                return path[i:] + [v]
            if v not in color:
                cyc = find_cycle(v)
                if cyc:
                    return cyc
        color[u] = 2
        path.pop()
        return None

    for c in sorted(mandatory):
        if c not in color:
            cycle = find_cycle(c)
            if cycle:
                raise PlanningError(
                    "conflict",
                    f"先修条件相互依赖形成回路，无法满足：{' -> '.join(cycle)}",
                    http_status=409,
                    details={"cycle": cycle},
                )

    # 2.3 同修关系（无向）形成的“同学期课程组”必须能放进同一个学期：
    #     学分之和不超上限，且开课春秋季有交集。
    adj = {c: set() for c in mandatory}
    for c in mandatory:
        for q in catalog[c].coreqs:
            if q in mandatory:
                adj[c].add(q)
                adj[q].add(c)

    remaining = set(mandatory)
    while remaining:
        root = min(remaining)
        comp: set[str] = set()
        comp_stack = [root]
        remaining.discard(root)
        while comp_stack:
            x = comp_stack.pop()
            comp.add(x)
            for q in adj[x]:
                if q in remaining:
                    remaining.discard(q)
                    comp_stack.append(q)

        codes = sorted(comp)
        total = sum(catalog[c].credits for c in comp)
        if total > credit_cap:
            raise PlanningError(
                "conflict",
                f"同修课程组 {{{', '.join(codes)}}} 合计 {total} 学分，"
                f"超过每学期上限 {credit_cap}，无法同学期安排。",
                http_status=409,
                details={"courses": codes, "total_credits": total, "credit_cap": credit_cap},
            )
        common_seasons = set(SEASONS)
        for c in comp:
            common_seasons &= set(catalog[c].seasons)
        if not common_seasons:
            raise PlanningError(
                "conflict",
                f"同修课程组 {{{', '.join(codes)}}} 没有共同开课的春秋季，无法同学期安排。",
                http_status=409,
                details={"courses": codes},
            )
        available = [i for i in range(n_terms) if season_at(i) in common_seasons]
        if not available:
            raise PlanningError(
                "no_solution",
                f"同修课程组 {{{', '.join(codes)}}} 仅在 {sorted(common_seasons)} 季开课，"
                f"在给定的 {n_terms} 个规划学期内没有可安排的学期。",
                http_status=422,
                details={"courses": codes, "common_seasons": sorted(common_seasons)},
            )

    # ------------------------------------------------------------------
    # 3) 可达课程全集（目标沿同修/先修引用可达且未修）
    # ------------------------------------------------------------------
    universe: set[str] = set()
    stack = list(need)
    while stack:
        c = stack.pop()
        if c in universe or c in completed:
            continue
        universe.add(c)
        for q in catalog[c].coreqs:
            if q not in completed and q not in universe:
                stack.append(q)
        for g in catalog[c].prereq_groups:
            if any(m in completed for m in g):
                continue
            for m in g:
                if m not in completed and m not in universe:
                    stack.append(m)

    # 反向先修引用：m -> [需要 m 作为先修的课程]
    reverse_req: dict[str, list[str]] = defaultdict(list)
    for c in universe:
        for g in catalog[c].prereq_groups:
            if any(m in completed for m in g):
                continue
            for m in g:
                if m in universe:
                    reverse_req[m].append(c)

    # ------------------------------------------------------------------
    # 4) 回溯搜索
    # ------------------------------------------------------------------
    def coreq_cluster(code: str, placement: dict[str, int], term: int):
        """沿同修引用求必须与 code 放在 term 的课程闭包。

        返回 (新课程, 已在该学期的锚点课程)；与既有安排冲突返回 None。
        """
        new: dict[str, int] = {}
        anchored: set[str] = set()
        seen: set[str] = set()
        st = [code]
        while st:
            x = st.pop()
            if x in completed or x in seen:
                continue
            seen.add(x)
            if x in placement:
                if placement[x] != term:
                    return None
                anchored.add(x)
                continue
            new[x] = term
            for q in catalog[x].coreqs:
                if q in completed:
                    continue
                if q in placement:
                    if placement[q] != term:
                        return None
                    anchored.add(q)
                elif q not in seen:
                    st.append(q)
        return new, anchored

    def try_place(placement: dict[str, int], code: str, term: int):
        cluster = coreq_cluster(code, placement, term)
        if cluster is None:
            return None
        new, anchored = cluster
        tentative = dict(placement)
        tentative.update(new)

        for x in new:
            if term >= n_terms:
                return None
            if season_at(term) not in catalog[x].seasons:
                return None
            # x 的每个先修组：已被已修课覆盖、或被更早学期的课覆盖；
            # 都不满足时必须仍有尚未安排的候选课程。
            for g in catalog[x].prereq_groups:
                if any(m in completed for m in g):
                    continue
                covered = any(tentative.get(m, -1) < term for m in g)
                if covered:
                    continue
                pending = [m for m in g if m not in completed and m not in tentative]
                if not pending:
                    return None
            # x 被某门已安排课程当作先修：x 必须严格早于该课程
            for r in reverse_req.get(x, ()):
                if r in tentative and tentative[r] <= term:
                    return None

        term_load = sum(
            catalog[c].credits for c, t in tentative.items() if t == term
        )
        if term_load > credit_cap:
            return None
        return tentative

    def justified(placement: dict[str, int]) -> bool:
        """叶节点裁剪：方案中每门课都必须是目标课或支撑目标课的必需课程。"""
        js = {c for c in need if c in placement}
        while True:
            added = False
            for x in list(js):
                for g in catalog[x].prereq_groups:
                    if any(m in completed for m in g):
                        continue
                    earlier = sorted(
                        m for m in g if m in placement and placement[m] < placement[x]
                    )
                    if not earlier:
                        return False
                    pick = earlier[0]
                    if pick not in js:
                        js.add(pick)
                        added = True
            # 被正当课程的同修链带入同一学期的课程同样正当
            for x in list(js):
                for q in catalog[x].coreqs:
                    if q in placement and placement[q] == placement[x] and q not in js:
                        js.add(q)
                        added = True
            if not added:
                break
        return js == set(placement)

    best_key: tuple[int, tuple] | None = None
    best_placement: dict[str, int] | None = None
    memo: set[frozenset] = set()
    calls = 0

    def search(placement: dict[str, int]) -> None:
        nonlocal best_key, best_placement, calls
        calls += 1
        if calls > _NODE_LIMIT:
            raise PlanningError(
                "no_solution",
                "搜索空间过大，超过节点上限，未能在规定时间内判定方案。",
                http_status=422,
            )

        state = frozenset(placement.items())
        if state in memo:
            return
        memo.add(state)

        # 最优界剪枝：已落位目标课的最大学期是最终完成期的下界（目标课在
        # 叶节点裁剪中永远保留），它严格大于已知最优完成期时不可能更优。
        if best_key is not None:
            placed_target_finish = -1
            for c, t in placement.items():
                if c in need and t > placed_target_finish:
                    placed_target_finish = t
            if placed_target_finish > best_key[0]:
                return

        # 4.1 先把所有未修目标课（连同修闭包）放进课表
        pending_targets = [t for t in sorted(need) if t not in placement]
        if pending_targets:
            t = pending_targets[0]
            for i in range(n_terms):
                nxt = try_place(placement, t, i)
                if nxt is not None:
                    search(nxt)
            return

        # 4.2 找第一个尚未满足的先修组，对每个候选课程 × 更早学期分支
        for x in sorted(placement, key=lambda c: (placement[c], c)):
            tx = placement[x]
            for g in catalog[x].prereq_groups:
                if any(m in completed for m in g):
                    continue
                if any(m in placement and placement[m] < tx for m in g):
                    continue
                candidates = sorted(
                    m for m in g if m not in completed and m not in placement
                )
                if not candidates:
                    return  # 该组已无任何可在更早学期安排的成员
                for m in candidates:
                    for i in range(tx):
                        nxt = try_place(placement, m, i)
                        if nxt is not None:
                            search(nxt)
                return

        # 4.3 完整方案：裁剪冗余课程后参与比较
        if not justified(placement):
            return
        finish = max(placement.values())
        lex_key = tuple(
            tuple(sorted(c for c, t in placement.items() if t == i))
            for i in range(finish + 1)
        )
        candidate_key = (finish, lex_key)
        if best_key is None or candidate_key < best_key:
            best_key = candidate_key
            best_placement = dict(placement)

    search({})

    if best_placement is None:
        raise PlanningError(
            "no_solution",
            f"在给定的 {n_terms} 个学期、每学期 {credit_cap} 学分上限内，"
            "无法完成全部目标课程的先修与同修要求，无完整方案。",
            http_status=422,
        )

    return _render(best_placement, start_year, start_season, start_semester, catalog)


def _render(
    placement: dict[str, int],
    start_year: int,
    start_season: str,
    start_semester: dict,
    catalog: dict[str, Course],
) -> dict:
    finish = max(placement.values())
    semesters = []
    for i in range(finish + 1):
        year, season = term_label(start_year, start_season, i)
        codes = sorted(c for c, t in placement.items() if t == i)
        semesters.append(
            {
                "index": i + 1,
                "year": year,
                "season": season,
                "courses": [
                    {
                        "code": c,
                        "name": catalog[c].name,
                        "credits": catalog[c].credits,
                    }
                    for c in codes
                ],
                "total_credits": sum(catalog[c].credits for c in codes),
            }
        )
    fyear, fseason = term_label(start_year, start_season, finish)
    return {
        "completed_already": False,
        "start_semester": start_semester,
        "completion_semester": _semester_dict(finish + 1, fyear, fseason),
        "semesters": semesters,
    }
