# 模块说明：Arena 出计划 Skill 加载与模板选型。
# plan_agent 每次生成必须加载 SKILL.md，并从 templates/ 六主题目录注入唯一种子课。

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_LOGGER = logging.getLogger("arena_plan_skill")

SKILL_ROOT = Path(__file__).resolve().parent.parent / "skills" / "arena-plan"
SKILL_MD = SKILL_ROOT / "SKILL.md"
DATA_ACCESS_MD = SKILL_ROOT / "data-access.md"
TEMPLATES_DIR = SKILL_ROOT / "templates"
INDEX_JSON = TEMPLATES_DIR / "index.json"

_GOAL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("learn", ("学游泳", "入门", "不会", "学习技术", "learn the technique", "learn")),
    ("technique", ("技术", "分解", "效率", "swolf", "提高技巧", "improve technique", "technique")),
    ("speed", ("速度", "冲刺", "配速", "speed", "sprint")),
    ("tone", ("减脂", "塑形", "燃脂", "tone", "calorie", "calories")),
    ("wellbeing", ("健康", "放松", "恢复", "福利", "well-being", "wellbeing", "recovery")),
    ("endurance", ("有氧", "耐力", "匀速", "长距离", "endurance", "aerobic")),
]

_DEFAULT_TEMPLATE = "arena-218"  # Endurance half-hour easy


def skill_root() -> Path:
    return SKILL_ROOT


def load_skill_md() -> str:
    """读取 SKILL.md 全文；缺失则抛错。"""
    if not SKILL_MD.is_file():
        raise FileNotFoundError(f"arena-plan Skill 缺失: {SKILL_MD}")
    text = SKILL_MD.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("arena-plan SKILL.md 为空")
    return text


@lru_cache(maxsize=1)
def _load_index() -> list[dict[str, Any]]:
    if not INDEX_JSON.is_file():
        raise FileNotFoundError(f"模板索引缺失: {INDEX_JSON}")
    data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    plans = data.get("plans") or []
    if not plans:
        raise RuntimeError("templates/index.json 无 plans")
    return plans


def _resolve_template_path(template_id: str) -> Path:
    """按 template_id（arena-{ref}）或相对 path 解析 YAML。"""
    tid = template_id.strip()
    for row in _load_index():
        if row.get("template_id") == tid or str(row.get("ref")) == tid.removeprefix("arena-"):
            rel = str(row.get("path") or "")
            # path 形如 templates/endurance/218-....yaml
            if rel.startswith("templates/"):
                path = SKILL_ROOT / rel
            else:
                path = TEMPLATES_DIR / rel
            if path.is_file():
                return path
    # 回退：递归搜 arena-{ref}.yaml 文件名含 ref
    ref = tid.removeprefix("arena-")
    matches = list(TEMPLATES_DIR.glob(f"**/{ref}-*.yaml"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"课程模板不存在: {template_id}")


def load_template(template_id: str) -> dict[str, Any]:
    """读取种子课 YAML（含 sections）。"""
    path = _resolve_template_path(template_id)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("sections"):
        raise RuntimeError(f"模板格式无效: {template_id}")
    data["template_id"] = str(data.get("template_id") or template_id)
    return data


def list_template_ids() -> list[str]:
    return sorted({str(p.get("template_id")) for p in _load_index() if p.get("template_id")})


def infer_goal_bucket(profile: dict[str, Any], user_request: str | None) -> str:
    blobs = [
        str(user_request or ""),
        str(profile.get("goal") or ""),
        str(profile.get("training_goal") or ""),
    ]
    text = " ".join(blobs).lower()
    for bucket, tips in _GOAL_RULES:
        if any(t.lower() in text for t in tips):
            return bucket
    return "endurance"


def _recent_distances(datapack: dict[str, Any] | None) -> list[float]:
    if not datapack:
        return []
    cards = (datapack.get("summary_cards") or {}).get("sessions") or []
    out: list[float] = []
    for card in cards:
        metrics = card.get("metrics") or {}
        dist = metrics.get("distance_m")
        if dist is None:
            continue
        try:
            out.append(float(dist))
        except (TypeError, ValueError):
            continue
    return out


def _notes_blob(datapack: dict[str, Any] | None) -> str:
    if not datapack:
        return ""
    parts: list[str] = []
    cards = datapack.get("summary_cards") or {}
    for card in (cards.get("sessions") or [])[:3]:
        for key in ("next_step", "endurance_note", "efficiency_note", "one_liner"):
            val = card.get(key)
            if val:
                parts.append(str(val))
    for card in cards.get("trends") or []:
        for key in ("load_note", "progress_note", "next_step", "one_liner"):
            val = card.get(key)
            if val:
                parts.append(str(val))
        if card.get("sample_insufficient"):
            parts.append("sample_insufficient")
    return "；".join(parts)


def infer_level(profile: dict[str, Any], datapack: dict[str, Any] | None, goal_bucket: str) -> str:
    # 档案难度偏好优先（easy/medium/hard）；未设置再自动推断
    pref = str((profile or {}).get("difficulty_pref") or "").strip().lower()
    if pref in ("easy", "medium", "hard"):
        return pref
    if goal_bucket == "learn":
        return "easy"
    notes = _notes_blob(datapack)
    if re.search(r"恢复|减量|疲劳|sample_insufficient", notes):
        return "easy"
    dists = _recent_distances(datapack)
    avg = sum(dists) / len(dists) if dists else None
    if avg is not None:
        if avg < 800:
            return "easy"
        if avg >= 2000:
            return "hard"
        return "medium"
    age = profile.get("age")
    try:
        if age is not None and int(age) >= 50:
            return "easy"
    except (TypeError, ValueError):
        pass
    return "medium"


def _band_mid(template: dict[str, Any]) -> float:
    band = template.get("volume_band_m") or [1200, 1800]
    try:
        return (float(band[0]) + float(band[1])) / 2.0
    except (TypeError, ValueError, IndexError):
        return 1500.0


def _candidates_for(goal_bucket: str, level: str, *, prefer_wellbeing: bool) -> list[str]:
    plans = _load_index()
    same = [p for p in plans if p.get("bucket") == goal_bucket]
    level_match = [p for p in same if p.get("level") == level]
    pool = level_match or same
    if prefer_wellbeing:
        wb = [p for p in plans if p.get("bucket") == "wellbeing"]
        pool = wb + pool
    if not pool:
        pool = [p for p in plans if p.get("template_id") == _DEFAULT_TEMPLATE] or plans
    # 按时长升序，短课优先贴近业余
    pool = sorted(pool, key=lambda p: (p.get("duration_min") is None, p.get("duration_min") or 999))
    return [str(p["template_id"]) for p in pool if p.get("template_id")]


def select_template_id(
    profile: dict[str, Any],
    *,
    user_request: str | None = None,
    datapack: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """返回 (template_id, goal_bucket, level)。"""
    goal_bucket = infer_goal_bucket(profile, user_request or (datapack or {}).get("user_request"))
    level = infer_level(profile, datapack, goal_bucket)
    notes = _notes_blob(datapack)
    req = str(user_request or (datapack or {}).get("user_request") or "")
    # 仅明确恢复/减量时才切 wellbeing；「疲劳/掉速」只降 level，仍留在当前目标桶
    prefer_wb = goal_bucket == "wellbeing" or bool(
        re.search(r"恢复|减量", notes + req) and goal_bucket != "speed"
    )
    candidates = _candidates_for(goal_bucket, level, prefer_wellbeing=prefer_wb)

    dists = _recent_distances(datapack)
    target = dists[0] if dists else None

    best_id = candidates[0] if candidates else _DEFAULT_TEMPLATE
    best_score = float("inf")
    for tid in candidates:
        try:
            tmpl = load_template(tid)
        except Exception:
            _LOGGER.exception("skip bad template %s", tid)
            continue
        mid = _band_mid(tmpl)
        band = tmpl.get("volume_band_m") or [0, 0]
        try:
            lo, hi = float(band[0]), float(band[1])
        except (TypeError, ValueError, IndexError):
            lo, hi = mid, mid
        if target is None:
            score = abs(mid - 1500.0)
        elif lo * 0.6 <= target <= hi * 1.3:
            score = abs(mid - target) * 0.5
        else:
            score = abs(mid - target)
        if score < best_score:
            best_score = score
            best_id = tid

    return best_id, goal_bucket, level


def template_seed_for_prompt(template: dict[str, Any]) -> str:
    slim = {
        "template_id": template.get("template_id"),
        "arena_ref": template.get("arena_ref"),
        "title": template.get("title"),
        "goal_bucket": template.get("goal_bucket"),
        "arena_goal": template.get("arena_goal"),
        "level": template.get("level"),
        "theme": template.get("theme"),
        "duration_min": template.get("duration_min"),
        "volume_band_m": template.get("volume_band_m"),
        "sections": template.get("sections") or [],
    }
    return yaml.safe_dump(slim, allow_unicode=True, sort_keys=False)


def build_plan_system_prompt() -> str:
    skill = load_skill_md()
    return (
        "你是游泳教练排课写手。必须严格遵循下方 Arena Plan Skill。\n"
        "运行时已由服务端选定唯一种子模板并附在用户消息中："
        "你只能在该模板 sections 骨架上调整，禁止从零另编课型。\n"
        "输出 Structured SwimTrainingPlan；注释简洁可上屏；不要写强度目标字段。\n"
        "种子 sections 里已有的 equipment（器材）与 drill_type（类型）必须原样保留，禁止一律填 null。\n"
        "不要编造摘要卡中没有的成绩数字。\n\n"
        "===== BEGIN SKILL.md =====\n"
        f"{skill}\n"
        "===== END SKILL.md ====="
    )


def build_plan_user_content(
    datapack_text: str,
    template: dict[str, Any],
    *,
    goal_bucket: str,
    level: str,
) -> str:
    seed = template_seed_for_prompt(template)
    return (
        "请根据 Data pack 与种子模板生成训练计划。\n"
        f"选型：goal_bucket={goal_bucket}, level={level}, "
        f"template_id={template.get('template_id')}。\n"
        "保留模板课型与组结构，按档案池长与摘要卡调整距离/次数/休息/注释。\n"
        "种子中的 equipment、drill_type 有值则原样输出（界面要显示「器材」「类型」）。\n\n"
        "----- DATA PACK -----\n"
        f"{datapack_text}\n\n"
        "----- SEED TEMPLATE -----\n"
        f"{seed}"
    )
