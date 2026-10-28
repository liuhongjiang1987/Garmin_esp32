# 模块级说明：综合建议档案摘要 + 训练计划异步任务 + 语音采访轮。
# 表盘：GET profile / POST turn / GET plan / POST analyze / GET status。

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from src.config import Settings, load_settings
from src.advice_datapack import build_advice_datapack
from src.plan_agent import (
    align_sections_to_pool,
    plan_to_ui_pages,
    profile_summary_text,
    run_plan_generation,
)
from src.repository.swim_repo import SwimRepository

_LOGGER = logging.getLogger("advice_queue")

# 薄采访槽位：核心齐了即可出计划；泳池可选。回复只追问一个缺口。
_SLOT_ORDER = ("age", "sex", "height_cm", "weight_kg", "goal")
_SLOT_ASK = {
    "age": "还想问一下您的年纪？",
    "sex": "方便说一下性别吗？",
    "height_cm": "身高大概多少厘米？",
    "weight_kg": "体重大概多少公斤？",
    "goal": "训练目标是什么？比如提高有氧或减脂。",
    "pool_length_m": "您常游的泳池大概几米？常见是25米或50米。",
}
_GOAL_HINTS = (
    ("提高有氧", "提高有氧"),
    ("有氧", "提高有氧"),
    ("减脂", "减脂"),
    ("减肥", "减脂"),
    ("技术", "改善技术"),
    ("改善技术", "改善技术"),
    ("自由泳", "提高自由泳"),
    ("铁人", "铁人三项备赛"),
    ("备赛", "备赛"),
    ("增肌", "增肌"),
    ("耐力", "提高耐力"),
)
_PLAN_INTENT = re.compile(r"出计划|给我计划|训练计划|开始分析|重新生成|做个计划|给我建议")

# 修改档案二级页 / 改档听不清时的可收集说明
MODIFY_GUIDE_TEXT = (
    "可修改：性别、年纪、身高、体重、泳池、训练目标、训练难度。"
    "例如：泳池三十米；难度高一点；太简单了。"
)

# 训练难度偏好：存盘 easy/medium/hard，表盘展示简单/中等/较难
_DIFFICULTY_CN = {"easy": "简单", "medium": "中等", "hard": "较难"}
_DIFFICULTY_LEVELS = frozenset(_DIFFICULTY_CN.keys())

STATUS_IDLE = "idle"
STATUS_ANALYZING = "analyzing"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

DEFAULT_ATHLETE = "default"

_plan_job_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(repo: SwimRepository) -> sqlite3.Connection:
    conn = sqlite3.connect(repo._db_paths.coach_db)
    conn.row_factory = sqlite3.Row
    return conn


def profile_fields_for_ui(profile: dict[str, Any] | None) -> list[dict[str, str]]:
    """档案详情翻页字段（标签/值）；空值省略。"""
    profile = profile or {}
    rows: list[dict[str, str]] = []
    sex = _profile_get(profile, "sex", "gender")
    if sex in ("男", "male", "M", "m"):
        rows.append({"label": "性别", "value": "男"})
    elif sex in ("女", "female", "F", "f"):
        rows.append({"label": "性别", "value": "女"})
    elif sex:
        rows.append({"label": "性别", "value": str(sex)})
    age = _profile_get(profile, "age")
    if age is not None:
        rows.append({"label": "年纪", "value": f"{age}岁"})
    pool = _profile_get(profile, "pool_length_m", "pool_length")
    if pool is not None:
        rows.append({"label": "泳池", "value": f"{int(pool)}米"})
    # 难度紧跟泳池：表盘每页 4 行，避免挤到第 2 页被忽略
    pref = _profile_get(profile, "difficulty_pref")
    if pref in _DIFFICULTY_CN:
        rows.append({"label": "训练难度", "value": _DIFFICULTY_CN[str(pref)]})
    height = _profile_get(profile, "height_cm", "height")
    if height is not None:
        rows.append({"label": "身高", "value": f"{int(height)}cm"})
    weight = _profile_get(profile, "weight_kg", "weight")
    if weight is not None:
        rows.append({"label": "体重", "value": f"{weight}kg"})
    goal = _profile_get(profile, "goal", "training_goal")
    if goal:
        rows.append({"label": "训练目标", "value": str(goal)})
    return rows


def get_advice_profile(repo: SwimRepository, athlete_id: str = DEFAULT_ATHLETE) -> dict[str, Any]:
    """表盘综合建议：无档案引导 / 有档案枢纽；fields 供档案详情翻页。"""
    profile = repo.get_profile(athlete_id) or {}
    summary = profile_summary_text(profile)
    datapack = build_advice_datapack(repo, profile)
    cards = datapack.get("summary_cards") or {}
    missing = missing_profile_slots(profile)
    return {
        "athlete_id": athlete_id,
        "has_profile": bool(summary),
        "slots_complete": not missing,
        "missing_slots": missing,
        "summary_text": summary,
        "guide_text": (
            "告诉我您的年纪、身高、体重、性别、训练目标，"
            "以及常游泳池大概几米，我可以给你一些训练建议。"
        ),
        "profile": profile,
        "fields": profile_fields_for_ui(profile),
        "modify_guide_text": MODIFY_GUIDE_TEXT,
        "datapack_meta": datapack.get("meta") or {},
        "headlines": datapack.get("headlines") or [],
        "summary_card_counts": {
            "sessions": len(cards.get("sessions") or []),
            "trends": len(cards.get("trends") or []),
        },
    }


def get_advice_datapack(
    repo: SwimRepository,
    athlete_id: str = DEFAULT_ATHLETE,
    *,
    user_request: str | None = None,
) -> dict[str, Any]:
    """语音轮 / 出计划用完整 Data pack（档案 + 单次/趋势摘要卡）。"""
    profile = repo.get_profile(athlete_id) or {}
    return build_advice_datapack(repo, profile, user_request=user_request)


def _profile_get(profile: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if profile.get(key) is not None and profile.get(key) != "":
            return profile.get(key)
    return None


def missing_profile_slots(profile: dict[str, Any] | None) -> list[str]:
    """尚未填的槽位，按采访优先级。"""
    profile = profile or {}
    missing: list[str] = []
    if _profile_get(profile, "age") is None:
        missing.append("age")
    if _profile_get(profile, "sex", "gender") is None:
        missing.append("sex")
    if _profile_get(profile, "height_cm", "height") is None:
        missing.append("height_cm")
    if _profile_get(profile, "weight_kg", "weight") is None:
        missing.append("weight_kg")
    if _profile_get(profile, "goal", "training_goal") is None:
        missing.append("goal")
    return missing


def extract_profile_slots(text: str) -> dict[str, Any]:
    """从一句口语里抽薄槽位；抽不到的字段不写入。"""
    text = (text or "").strip()
    out: dict[str, Any] = {}
    if not text:
        return out

    m = re.search(r"(?:年纪|年龄)?\s*(\d{1,3})\s*岁", text)
    if not m:
        m = re.search(r"(?:我|今年)\s*(\d{1,3})\s*(?:岁|了)", text)
    if m:
        age = int(m.group(1))
        if 5 <= age <= 100:
            out["age"] = age

    m = re.search(r"(?:身高)?\s*(\d{2,3})\s*(?:cm|CM|厘米|公分)", text)
    if not m:
        m = re.search(r"身高\s*(\d{2,3})", text)
    if m:
        height = int(m.group(1))
        if 100 <= height <= 230:
            out["height_cm"] = height

    m = re.search(r"(?:体重)?\s*(\d{2,3}(?:\.\d)?)\s*(?:kg|KG|公斤|千克)", text)
    if not m:
        m = re.search(r"体重\s*(\d{2,3}(?:\.\d)?)", text)
    if m:
        weight = float(m.group(1))
        if 30 <= weight <= 200:
            out["weight_kg"] = int(weight) if weight == int(weight) else weight

    if re.search(r"女性|女的|我是女|性别女", text):
        out["sex"] = "女"
    elif re.search(r"男性|男的|我是男|性别男", text):
        out["sex"] = "男"

    # 泳池：先抓「泳池/池长 + N米」（15–100，含 30 米等非常规池）；再匹配 25/50 别称。
    m = re.search(
        r"(?:泳池|池长|泳道|池子|常游|游的)\s*(?:是|大约|大概|差不多)?\s*(\d{2}(?:\.\d)?)\s*(?:米|公尺|m|M)",
        text,
    )
    if not m:
        m = re.search(r"(\d{2}(?:\.\d)?)\s*(?:米|公尺|m|M)\s*(?:的)?\s*(?:泳池|池|泳道)", text)
    if m:
        pool = float(m.group(1))
        if 15 <= pool <= 100:
            out["pool_length_m"] = int(pool) if pool == int(pool) else pool
    elif re.search(r"短池|(?:25|二五|廿五|二十五)\s*(?:米|公尺|m|M)", text) or (
        re.search(r"(?:25|二五|廿五|二十五)", text) and re.search(r"池", text)
    ):
        out["pool_length_m"] = 25
    elif re.search(r"长池|奥运池|(?:50|五十)\s*(?:米|公尺|m|M)", text) or (
        re.search(r"(?:50|五十)", text) and re.search(r"池", text)
    ):
        out["pool_length_m"] = 50
    elif re.search(r"标准池", text) and not re.search(r"(?:25|二五|廿五|二十五|50|五十|\d{2})", text):
        out["pool_length_m"] = 50
    else:
        # 纯「三十米/25米」：有「池」上下文或中文数词时再收
        m = re.search(r"(?:三十|廿五|二五|二十五|五十)\s*(?:米|公尺)", text)
        if m:
            word = m.group(0)
            if "五十" in word:
                out["pool_length_m"] = 50
            elif "三十" in word:
                out["pool_length_m"] = 30
            else:
                out["pool_length_m"] = 25
        else:
            m = re.search(r"(?<!\d)(\d{2})\s*(?:米|公尺|m|M)(?!\d)", text)
            if m and re.search(r"池|泳", text):
                pool = int(m.group(1))
                if 15 <= pool <= 100:
                    out["pool_length_m"] = pool

    for tip, goal in _GOAL_HINTS:
        if tip in text:
            out["goal"] = goal
            break
    if "goal" not in out:
        m = re.search(r"(?:训练目标|目标是|目标[:：]|想要|希望)\s*([^，。！？\n]{2,40})", text)
        if m:
            out["goal"] = m.group(1).strip(" ，。！？")

    # 难度偏好：更难 / 适中 / 更易（互斥优先级：明确「太难」降级优先于「难一点」）
    if re.search(r"太难|难度太高|简单(?:一点|点|些)|轻松(?:一点|点|些)|降难度|容易点", text):
        out["difficulty_pref"] = "easy"
    elif re.search(r"中等难度|难度中等|适中|一般难度", text):
        out["difficulty_pref"] = "medium"
    elif re.search(
        r"太简单|简单了|难度(?:高|大)一点|要难一点|难一点|加强|较难|难度高|提高难度|难一些",
        text,
    ):
        out["difficulty_pref"] = "hard"
    elif re.search(r"难度\s*(?:要|改成|设为|设成)?\s*(简单|中等|较难|困难)", text):
        word = re.search(r"难度\s*(?:要|改成|设为|设成)?\s*(简单|中等|较难|困难)", text)
        if word:
            mapping = {"简单": "easy", "中等": "medium", "较难": "hard", "困难": "hard"}
            out["difficulty_pref"] = mapping[word.group(1)]

    return out


def _ask_next_slot(missing: list[str]) -> str:
    if not missing:
        return "档案齐了，需要的话可以说「给我出计划」。"
    return _SLOT_ASK.get(missing[0], "还想补充一点档案信息吗？")


def _slot_confirm_text(slots: dict[str, Any]) -> str:
    """已写入槽位的短确认（TTS/屏显）。"""
    parts: list[str] = []
    if "sex" in slots:
        parts.append(f"性别{slots['sex']}")
    if "age" in slots:
        parts.append(f"年纪{slots['age']}岁")
    if "height_cm" in slots:
        parts.append(f"身高{slots['height_cm']}厘米")
    if "weight_kg" in slots:
        parts.append(f"体重{slots['weight_kg']}公斤")
    if "pool_length_m" in slots:
        parts.append(f"泳池{slots['pool_length_m']}米")
    if "goal" in slots:
        parts.append(f"目标{slots['goal']}")
    if "difficulty_pref" in slots:
        pref = slots["difficulty_pref"]
        parts.append(f"难度{_DIFFICULTY_CN.get(str(pref), str(pref))}")
    return "、".join(parts)


def run_advice_turn(
    repo: SwimRepository,
    text: str,
    *,
    athlete_id: str = DEFAULT_ATHLETE,
    settings: Settings | None = None,
    use_demo: bool = False,
    mode: str = "interview",
) -> dict[str, Any]:
    """表盘综合建议一句话：更新槽位 → 短回复 → 可选触发出计划。

    mode=interview|modify：modify 时抽不到槽位会 keep_listening，避免空转回枢纽。
    """
    settings = settings or load_settings()
    utterance = (text or "").strip()
    profile = dict(repo.get_profile(athlete_id) or {})
    slots = extract_profile_slots(utterance)
    modify = (mode or "").strip().lower() == "modify"
    if slots:
        profile.update(slots)
        # 统一字段名，避免 sex/gender 分叉
        if "sex" in slots:
            profile["sex"] = slots["sex"]
            profile.pop("gender", None)
        if "goal" in slots:
            profile["goal"] = slots["goal"]
            profile.pop("training_goal", None)
        if "pool_length_m" in slots:
            profile["pool_length_m"] = slots["pool_length_m"]
            profile.pop("pool_length", None)
        if "difficulty_pref" in slots:
            pref = str(slots["difficulty_pref"]).strip().lower()
            if pref in _DIFFICULTY_LEVELS:
                profile["difficulty_pref"] = pref
            else:
                profile.pop("difficulty_pref", None)
                slots.pop("difficulty_pref", None)
        repo.upsert_profile(athlete_id, profile)
        _LOGGER.info(
            "advice turn mode=%s slots=%s text=%r athlete=%s",
            mode,
            list(slots.keys()),
            utterance[:80],
            athlete_id,
        )
    else:
        _LOGGER.info(
            "advice turn mode=%s slots=[] text=%r athlete=%s",
            mode,
            utterance[:80],
            athlete_id,
        )

    missing = missing_profile_slots(profile)
    summary = profile_summary_text(profile)
    has_profile = bool(summary)
    want_plan = bool(_PLAN_INTENT.search(utterance))
    start_plan = False
    keep_listening = False

    pool_missing = _profile_get(profile, "pool_length_m", "pool_length") is None
    confirm = _slot_confirm_text(slots)

    if not utterance:
        reply = "没有听清，再说一次？"
        keep_listening = modify
    elif want_plan and not has_profile:
        reply = "先告诉我年纪、身高、体重、性别和训练目标，再给你出计划。"
    elif want_plan and has_profile:
        start_plan = True
        reply = "好的，我开始为你整理训练建议。"
    elif modify and slots:
        reply = f"已记下{confirm}。"
        keep_listening = False
    elif modify and not slots:
        reply = "没听清。" + MODIFY_GUIDE_TEXT
        keep_listening = True
    elif slots and not missing:
        # 齐档后回枢纽；不自动出计划。泳池可选追问一句。
        if confirm:
            reply = f"已记下{confirm}。"
        else:
            reply = "档案齐了。"
        if pool_missing:
            reply += _SLOT_ASK["pool_length_m"] + "也可以稍后在菜单里生成训练计划。"
        else:
            reply += "可在菜单里查看档案或生成训练计划。"
    elif slots:
        reply = f"好的，已记下{confirm}。" + _ask_next_slot(missing)
    elif missing:
        reply = "我没太听清关键信息。" + _ask_next_slot(missing)
    elif pool_missing and has_profile:
        reply = _SLOT_ASK["pool_length_m"]
        keep_listening = modify
    else:
        reply = "可以说训练目标，或说「给我出计划」。"
        keep_listening = modify

    plan_status: dict[str, Any]
    if start_plan:
        plan_status = request_plan_analysis(
            repo,
            settings,
            athlete_id=athlete_id,
            use_demo=use_demo,
        )
    else:
        plan_status = get_plan_status(repo, athlete_id)

    guide = (
        "告诉我您的年纪、身高、体重、性别、训练目标，"
        "以及常游泳池大概几米，我可以给你一些训练建议。"
    )
    return {
        "athlete_id": athlete_id,
        "has_profile": has_profile,
        "summary_text": summary,
        "guide_text": guide if not modify else MODIFY_GUIDE_TEXT,
        "fields": profile_fields_for_ui(profile),
        "reply_text": reply,
        "slots_complete": not missing,
        "missing_slots": missing,
        "updated_fields": list(slots.keys()),
        "start_plan": start_plan,
        "keep_listening": keep_listening,
        "plan_status": plan_status,
        "profile": profile,
    }


def get_plan_status(repo: SwimRepository, athlete_id: str = DEFAULT_ATHLETE) -> dict[str, Any]:
    """CTA 状态：idle|analyzing|succeeded|failed。"""
    with _connect(repo) as conn:
        row = conn.execute(
            "SELECT status, error, plan_id FROM advice_plan_jobs WHERE athlete_id = ?",
            (athlete_id,),
        ).fetchone()
        latest = conn.execute(
            """
            SELECT plan_id, created_at FROM workout_plans
            WHERE athlete_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (athlete_id,),
        ).fetchone()
    if row is None:
        status = STATUS_SUCCEEDED if latest else STATUS_IDLE
        return {
            "status": status,
            "can_open": latest is not None,
            "plan_id": latest["plan_id"] if latest else None,
            "error": None,
        }
    status = row["status"]
    plan_id = row["plan_id"] or (latest["plan_id"] if latest else None)
    # 有旧计划即可打开；analyzing 时仍可看上一份，同时「更新计划」显示转圈。
    can_open = latest is not None
    if status == STATUS_IDLE and latest is not None:
        status = STATUS_SUCCEEDED
    if status == STATUS_SUCCEEDED and not can_open:
        status = STATUS_IDLE
    return {
        "status": status,
        "can_open": can_open,
        "plan_id": plan_id or (latest["plan_id"] if latest else None),
        "error": row["error"],
    }


def get_latest_plan(repo: SwimRepository, athlete_id: str = DEFAULT_ATHLETE) -> dict[str, Any] | None:
    """取最新计划 + UI 翻页 pages。"""
    with _connect(repo) as conn:
        row = conn.execute(
            """
            SELECT plan_id, plan_json, created_at FROM workout_plans
            WHERE athlete_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (athlete_id,),
        ).fetchone()
    if row is None:
        return None
    body = json.loads(row["plan_json"])
    profile = repo.get_profile(athlete_id) or {}
    pool = profile.get("pool_length_m") or profile.get("pool_length")
    # 展示层按当前泳池对齐；sections 同步返回对齐后的值，避免表盘/API 不一致
    sections = align_sections_to_pool(list(body.get("sections") or []), pool)
    view = dict(body)
    view["sections"] = sections
    return {
        "plan_id": row["plan_id"],
        "created_at": row["created_at"],
        "sections": sections,
        "pages": plan_to_ui_pages(view, pool_length_m=pool),
    }


def _save_plan(repo: SwimRepository, athlete_id: str, plan: dict[str, Any]) -> None:
    plan_id = plan["plan_id"]
    created = plan.get("created_at") or _now()
    with _connect(repo) as conn:
        conn.execute(
            """
            INSERT INTO workout_plans(
                plan_id, athlete_id, based_on_activity_id, plan_markdown, plan_json, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET plan_json=excluded.plan_json
            """,
            (
                plan_id,
                athlete_id,
                "",  # markdown 留空；表盘只用 json
                json.dumps(plan, ensure_ascii=False),
                created,
            ),
        )
        conn.execute(
            """
            INSERT INTO advice_plan_jobs(athlete_id, status, error, plan_id, created_at, updated_at)
            VALUES (?, ?, NULL, ?, ?, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                status=excluded.status,
                error=NULL,
                plan_id=excluded.plan_id,
                updated_at=excluded.updated_at
            """,
            (athlete_id, STATUS_SUCCEEDED, plan_id, created, _now()),
        )
        conn.commit()


def _set_job(
    repo: SwimRepository,
    athlete_id: str,
    status: str,
    *,
    error: str | None = None,
    plan_id: str | None = None,
) -> None:
    now = _now()
    with _connect(repo) as conn:
        conn.execute(
            """
            INSERT INTO advice_plan_jobs(athlete_id, status, error, plan_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                status=excluded.status,
                error=excluded.error,
                plan_id=COALESCE(excluded.plan_id, advice_plan_jobs.plan_id),
                updated_at=excluded.updated_at
            """,
            (athlete_id, status, error, plan_id, now, now),
        )
        conn.commit()


def _run_plan_job(repo: SwimRepository, settings: Settings, athlete_id: str, use_demo: bool) -> None:
    with _plan_job_lock:
        try:
            profile = repo.get_profile(athlete_id) or {}
            # §3.2：出计划前装包——档案 + 已算好的单次/趋势摘要卡
            datapack = build_advice_datapack(repo, profile)
            plan = run_plan_generation(
                profile,
                datapack=datapack,
                settings=settings,
                use_demo=use_demo,
            )
            _save_plan(repo, athlete_id, plan)
            _LOGGER.info(
                "advice plan ready athlete=%s plan_id=%s cards=%s",
                athlete_id,
                plan.get("plan_id"),
                datapack.get("meta"),
            )
        except Exception as exc:
            _LOGGER.exception("advice plan job failed")
            _set_job(repo, athlete_id, STATUS_FAILED, error=type(exc).__name__)


def request_plan_analysis(
    repo: SwimRepository,
    settings: Settings | None = None,
    *,
    athlete_id: str = DEFAULT_ATHLETE,
    use_demo: bool = False,
) -> dict[str, Any]:
    """点 CTA / 语音触发：入队 analyzing 并后台生成。"""
    settings = settings or load_settings()
    st = get_plan_status(repo, athlete_id)
    if st["status"] == STATUS_ANALYZING:
        return {**st, "started": False}
    _set_job(repo, athlete_id, STATUS_ANALYZING)
    threading.Thread(
        target=_run_plan_job,
        args=(repo, settings, athlete_id, use_demo),
        daemon=True,
        name=f"plan-{athlete_id}",
    ).start()
    return {**get_plan_status(repo, athlete_id), "started": True}


def ensure_demo_plan(repo: SwimRepository, athlete_id: str = DEFAULT_ATHLETE) -> dict[str, Any]:
    """开发联调：无计划时写入设计稿示例，便于立刻翻页。"""
    existing = get_latest_plan(repo, athlete_id)
    if existing is not None:
        return existing
    plan = run_plan_generation({}, use_demo=True)
    _save_plan(repo, athlete_id, plan)
    return get_latest_plan(repo, athlete_id) or {
        "plan_id": plan["plan_id"],
        "created_at": plan["created_at"],
        "sections": plan["sections"],
        "pages": plan_to_ui_pages(plan),
    }
