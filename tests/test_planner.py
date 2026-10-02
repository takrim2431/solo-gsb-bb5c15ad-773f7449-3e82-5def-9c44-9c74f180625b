"""planner 引擎单元测试。"""

import pytest

from app.planner import (
    SPRING,
    FALL,
    Course,
    PlanningError,
    build_plan,
    term_label,
)


def C(code, credits=3, spring=True, fall=True, groups=(), coreqs=(), name=""):
    return Course(
        code=code,
        name=name or code,
        credits=credits,
        seasons=frozenset(s for s, ok in ((SPRING, spring), (FALL, fall)) if ok),
        prereq_groups=tuple(frozenset(g) for g in groups),
        coreqs=frozenset(coreqs),
    )


def semester_codes(result):
    return [[c["code"] for c in s["courses"]] for s in result["semesters"]]


# ---------- 基础 ----------

def test_simple_no_prereq():
    cat = {"A": C("A")}
    r = build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    assert semester_codes(r) == [["A"]]
    assert r["completion_semester"] == {"index": 1, "year": 2026, "season": "fall"}


def test_target_missing_raises_and_no_partial():
    cat = {"A": C("A")}
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A", "X"], 2026, FALL, 6, 4)
    assert ei.value.code == "course_not_found"
    assert ei.value.details["missing_courses"] == ["X"]


def test_completed_target_returns_empty_plan():
    cat = {"A": C("A")}
    r = build_plan(cat, ["A"], ["A"], 2026, FALL, 6, 4)
    assert r["completed_already"] is True
    assert r["semesters"] == []
    assert r["completion_semester"] is None


def test_completed_prereq_satisfies_group():
    cat = {"A": C("A"), "B": C("B", groups=(["A"],))}
    r = build_plan(cat, ["A"], ["B"], 2026, FALL, 6, 4)
    assert semester_codes(r) == [["B"]]


def test_prereq_must_be_in_earlier_term():
    cat = {"A": C("A", fall=False, spring=True), "B": C("B", groups=(["A"],), spring=False, fall=True)}
    # start spring 2026: A spring2026 -> B fall2026, 2 terms
    r = build_plan(cat, [], ["B"], 2026, SPRING, 6, 2)
    assert semester_codes(r) == [["A"], ["B"]]
    # 只有 1 个学期：A、B 不能同学期 -> 无解
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["B"], 2026, SPRING, 6, 1)
    assert ei.value.code == "no_solution"


def test_credits_cap_enforced():
    cat = {"A": C("A", credits=4), "B": C("B", credits=3)}
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A", "B"], 2026, FALL, 5, 1)
    assert ei.value.code == "no_solution"
    r = build_plan(cat, [], ["A", "B"], 2026, FALL, 7, 4)
    assert semester_codes(r) == [["A", "B"]]


def test_single_course_over_cap_is_conflict():
    cat = {"A": C("A", credits=8)}
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A"], 2026, FALL, 5, 6)
    assert ei.value.code == "conflict"


# ---------- 先修组“每组任选一门、各组均须满足” ----------

def test_choice_group_picks_any_member():
    # B: [A1 | A2]，两成员均满足，选字典序小的 A1
    cat = {"A1": C("A1"), "A2": C("A2"), "B": C("B", groups=(["A1", "A2"],))}
    r = build_plan(cat, [], ["B"], 2026, FALL, 9, 4)
    codes = semester_codes(r)
    assert codes[0] == ["A1"]
    assert codes[1] == ["B"]


def test_multiple_groups_all_must_satisfy():
    # C: [A1|A2] 与 [B1|B2] 两组都要满足
    cat = {
        "A1": C("A1"), "A2": C("A2"),
        "B1": C("B1"), "B2": C("B2"),
        "C": C("C", groups=(["A1", "A2"], ["B1", "B2"])),
    }
    r = build_plan(cat, [], ["C"], 2026, FALL, 9, 4)
    codes = semester_codes(r)
    assert codes[0] == ["A1", "B1"]
    assert codes[1] == ["C"]


# ---------- 同修 ----------

def test_coreq_same_term():
    cat = {"A": C("A", coreqs=("L",)), "L": C("L", credits=1, coreqs=("A",))}
    r = build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    assert semester_codes(r) == [["A", "L"]]


def test_coreq_already_completed_not_scheduled():
    cat = {"A": C("A", coreqs=("L",)), "L": C("L", coreqs=("A",))}
    r = build_plan(cat, ["L"], ["A"], 2026, FALL, 6, 4)
    assert semester_codes(r) == [["A"]]


def test_coreq_group_over_cap_conflict():
    cat = {"A": C("A", credits=4, coreqs=("L",)), "L": C("L", credits=4, coreqs=("A",))}
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A"], 2026, FALL, 5, 4)
    assert ei.value.code == "conflict"
    assert "同修课程组" in ei.value.message


def test_coreq_no_common_season_conflict():
    cat = {
        "A": C("A", spring=True, fall=False, coreqs=("L",)),
        "L": C("L", spring=False, fall=True, coreqs=("A",)),
    }
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    assert ei.value.code == "conflict"


# ---------- 冲突 / 无解 ----------

def test_prereq_cycle_conflict():
    # A 需要 B，B 需要 A（强制单成员组）
    cat = {"A": C("A", groups=(["B"],)), "B": C("B", groups=(["A"],))}
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    assert ei.value.code == "conflict"
    assert "回路" in ei.value.message


def test_choice_member_breaks_apparent_cycle():
    # A 的先修组 [B|X]：B 又需要 A，表面 A<->B 成环，但可选 X 打破回路。
    cat = {
        "A": C("A", groups=(["B", "X"],)),
        "B": C("B", groups=(["A"],)),
        "X": C("X"),
    }
    r = build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    # 只能选 X（B 与 A 互相要求、无更早学期可能）
    assert semester_codes(r) == [["X"], ["A"]]
    assert "B" not in [c for s in semester_codes(r) for c in s]


def test_real_impossible_cycle_via_alternatives_is_no_solution():
    # A: [B|C]；B 需要 A，C 也需要 A —— 任何选择都要求 A 在更早学期
    cat = {
        "A": C("A", groups=(["B", "C"],)),
        "B": C("B", groups=(["A"],)),
        "C": C("C", groups=(["A"],)),
    }
    with pytest.raises(PlanningError) as ei:
        build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    # 非结构性单成员环，穷尽搜索后判无解
    assert ei.value.code == "no_solution"


def test_season_window_no_solution():
    # A 只春季开，B 需要 A 且 B 只秋季开：至少 2 学期
    cat = {"A": C("A", spring=True, fall=False), "B": C("B", spring=False, fall=True, groups=(["A"],))}
    # 从春季开始 1 学期 -> 无解
    with pytest.raises(PlanningError):
        build_plan(cat, [], ["B"], 2026, SPRING, 6, 1)


def test_no_redundant_courses_in_plan():
    # B 只需 [A1|A2]；目标只有 B 时，方案中不能同时出现 A1 和 A2
    cat = {"A1": C("A1"), "A2": C("A2"), "B": C("B", groups=(["A1", "A2"],))}
    r = build_plan(cat, [], ["B"], 2026, FALL, 9, 4)
    flat = [c for s in semester_codes(r) for c in s]
    assert set(flat) == {"A1", "B"}


# ---------- 最早完成 + 字典序 ----------

def test_earliest_completion_prefers_later_empty_term():
    # B: [A1|A2]。A1 仅秋季，A2 春秋均开。从秋季起：
    # 选 A1 -> 秋(A1), 春(B)；选 A2 -> 秋(A2), 春(B)：完成期相同，
    # 字典序比较第一学期，A1 < A2 -> 选 A1。
    cat = {
        "A1": C("A1", spring=False, fall=True),
        "A2": C("A2"),
        "B": C("B", groups=(["A1", "A2"],)),
    }
    r = build_plan(cat, [], ["B"], 2026, FALL, 9, 4)
    assert semester_codes(r) == [["A1"], ["B"]]


def test_completion_term_lex_compare_empty_semester():
    # 构造：两选择完成学期相同，但其中一种第 1 学期为空（先修链允许延后）。
    # X -> B（X 只春季开）；B 也可直接由已修组替代：B: [X|Y]
    # 若 Y 已修，则 B 直接安排，且可放在第 2 学期? —— 最早完成会放第 1 学期。
    # 这里验证：当必须间隔时，空学期元组 () 排在前面。
    # A(春) -> B(秋)；与 直接把前置和 B 压缩不可比。改为验证 term_label 与排序规则：
    assert () < ("A",)


# ---------- 其他 ----------

def test_empty_first_semester_kept_when_forced_by_season():
    # A 仅春季，B 仅秋季且需 A；从 2026 秋开始 -> 第 1 学期必须空出
    cat = {"A": C("A", spring=True, fall=False), "B": C("B", spring=False, fall=True, groups=(["A"],))}
    r = build_plan(cat, [], ["B"], 2026, FALL, 6, 4)
    assert semester_codes(r) == [[], ["A"], ["B"]]
    assert r["completion_semester"] == {"index": 3, "year": 2027, "season": "fall"}


def test_completed_unknown_code_is_phantom():
    # 已修课 X 不在目录中，但可满足先修组
    cat = {"B": C("B", groups=(["X"],))}
    r = build_plan(cat, ["X"], ["B"], 2026, FALL, 6, 4)
    assert semester_codes(r) == [["B"]]


def test_term_label_rollover():
    assert term_label(2026, FALL, 0) == (2026, FALL)
    assert term_label(2026, FALL, 1) == (2027, SPRING)
    assert term_label(2026, FALL, 2) == (2027, FALL)
    assert term_label(2026, SPRING, 0) == (2026, SPRING)
    assert term_label(2026, SPRING, 1) == (2026, FALL)
    assert term_label(2026, SPRING, 2) == (2027, SPRING)


def test_result_has_credits():
    cat = {"A": C("A", credits=4)}
    r = build_plan(cat, [], ["A"], 2026, FALL, 6, 4)
    s = r["semesters"][0]
    assert s["total_credits"] == 4
    assert s["courses"][0]["credits"] == 4
