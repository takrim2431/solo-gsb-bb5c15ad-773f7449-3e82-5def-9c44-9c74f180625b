"""Pydantic 请求模型与输入校验。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from .planner import SPRING, FALL

SEASON_VALUES = {SPRING, FALL}


class SemesterIn(BaseModel):
    year: int = Field(..., ge=1900, le=2999, description="学年，例如 2026")
    season: str = Field(..., description="开课季节：spring（春季）或 fall（秋季）")

    @field_validator("season")
    @classmethod
    def _season(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SEASON_VALUES:
            raise ValueError("season 只能是 'spring' 或 'fall'")
        return v


class CourseIn(BaseModel):
    code: str = Field(..., min_length=1)
    name: str = Field("", description="课程名称（可选）")
    credits: int = Field(..., gt=0, description="学分，必须为正整数")
    spring: bool = Field(False, description="是否春季开课")
    fall: bool = Field(False, description="是否秋季开课")
    # 每个内层列表是一组先修：组内任选一门；各组都必须满足
    prereq_groups: list[list[str]] = Field(default_factory=list)
    coreqs: list[str] = Field(default_factory=list, description="同修课程代码列表")

    @field_validator("code", "name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        return v

    @field_validator("prereq_groups")
    @classmethod
    def _groups(cls, v: list[list[str]]) -> list[list[str]]:
        cleaned: list[list[str]] = []
        for g in v:
            members = sorted({m.strip() for m in g if m.strip()})
            if not members:
                raise ValueError("先修课组不能为空组")
            cleaned.append(members)
        return cleaned

    @field_validator("coreqs")
    @classmethod
    def _coreqs(cls, v: list[str]) -> list[str]:
        out = sorted({c.strip() for c in v if c.strip()})
        return out


class CatalogCreate(BaseModel):
    note: str = Field("", description="版本说明（可选）")
    courses: list[CourseIn] = Field(..., min_length=1, description="课程目录（至少一门课）")

    @field_validator("courses")
    @classmethod
    def _unique_codes(cls, v: list[CourseIn]) -> list[CourseIn]:
        codes = [c.code for c in v]
        if len(codes) != len(set(codes)):
            dupes = sorted({c for c in codes if codes.count(c) > 1})
            raise ValueError(f"课程代码重复：{', '.join(dupes)}")
        return v


class PlanCreate(BaseModel):
    completed_courses: list[str] = Field(default_factory=list, description="已修课程代码")
    target_courses: list[str] = Field(..., min_length=1, description="目标课程代码（非空）")
    start_semester: SemesterIn
    credit_cap: int = Field(..., gt=0, description="每学期学分上限，必须为正")
    planning_terms: int = Field(..., gt=0, description="规划学期数，必须为正")

    @field_validator("completed_courses", "target_courses")
    @classmethod
    def _strip_list(cls, v: list[str]) -> list[str]:
        out = [x.strip() for x in v if x.strip()]
        if any(" " in x for x in out):
            raise ValueError("课程代码不能包含空白字符")
        return out

    @model_validator(mode="after")
    def _targets_nonempty_after_cleanup(self) -> "PlanCreate":
        # 形如 ["", "  "] 的输入会被字段校验清洗为空，必须在此再拦一次
        if not self.target_courses:
            raise ValueError("target_courses 清洗后为空，目标课程必须非空")
        return self
