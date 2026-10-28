# 模块级说明：综合建议「训练计划」专用 Agent。
# 输入档案 + 诉求 → Structured SwimTrainingPlan；服务端补 plan_id/created_at。
# 禁止从口语自由文本解析计划。

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.arena_plan_skill import (
    build_plan_system_prompt,
    build_plan_user_content,
    load_template,
    select_template_id,
)
from src.config import Settings, load_settings

_LOGGER = logging.getLogger("plan_agent")

Stroke = Literal[
    "自由泳",
    "蛙泳",
    "仰泳",
    "蝶泳",
    "选项",
    "混合泳 (IM)",
    "IM/趟",
    "逆序个人混合泳 (RIMO)",
    "混合泳",
]
DrillType = Literal["踢动", "划水", "分解动作"]
Equipment = Literal["脚蹼", "浮板", "手蹼", "8字板", "呼吸管"]
SectionKind = Literal["warmup", "main", "cooldown"]

KIND_TITLE = {"warmup": "热身", "main": "主要", "cooldown": "放松"}


class PlanSection(BaseModel):
    """训练计划单板块（热身/主要/放松）。"""

    kind: SectionKind
    repeat: int | None = Field(default=None, ge=1)
    distance_m: float | None = Field(default=None, ge=0)
    stroke: Stroke | None = Field(default=None, description="泳姿；界面「泳姿」")
    drill_type: DrillType | None = Field(
        default=None, description="训练类型；界面「类型」；种子有则保留"
    )
    equipment: Equipment | None = Field(
        default=None,
        description="器材；界面「器材」；枚举脚蹼/浮板/手蹼/8字板/呼吸管；种子有则必须保留，勿一律填 null",
    )
    note: str | None = Field(default=None, max_length=200)
    rest_s: int | None = Field(default=None, ge=0)


class SwimTrainingPlan(BaseModel):
    """结构化课表；对齐 design 热身/主要/放松翻页。"""

    sections: list[PlanSection] = Field(min_length=1)


def design_demo_plan() -> dict[str, Any]:
    """设计稿 FuWw8/BPJ3a/GDaYB/x5MdX8/AoZhj 示例课表（联调与无模型时用）。"""
    return {
        "sections": [
            {
                "kind": "warmup",
                "repeat": None,
                "distance_m": 240,
                "stroke": "自由泳",
                "drill_type": None,
                "equipment": None,
                "note": "轻松自由泳",
                "rest_s": None,
            },
            {
                "kind": "warmup",
                "repeat": None,
                "distance_m": 120,
                "stroke": "选项",
                "drill_type": None,
                "equipment": None,
                "note": "4×30米加速",
                "rest_s": None,
            },
            {
                "kind": "main",
                "repeat": 3,
                "distance_m": 120,
                "stroke": "自由泳",
                "drill_type": "分解动作",
                "equipment": "浮板",
                "note": "30米打腿 + 30米单臂 + 60米配合",
                "rest_s": 15,
            },
            {
                "kind": "cooldown",
                "repeat": None,
                "distance_m": 180,
                "stroke": "选项",
                "drill_type": None,
                "equipment": None,
                "note": "放松游",
                "rest_s": None,
            },
        ]
    }


def _schema_dict() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "schemas" / "swim_plan.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _chat_model(settings: Settings) -> ChatOpenAI:
    if not settings.model_api_key or not settings.model_base_url:
        raise RuntimeError("缺少 SILICONFLOW_API_KEY 或 SILICONFLOW_BASE_URL")
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        temperature=0.3,
    )


def create_plan_agent(settings: Settings | None = None):
    """创建出计划 Agent（Structured output；系统提示强制加载 arena-plan/SKILL.md）。"""
    settings = settings or load_settings()
    model = _chat_model(settings)
    return create_agent(
        model=model,
        tools=[],
        system_prompt=build_plan_system_prompt(),
        response_format=ToolStrategy(SwimTrainingPlan),
    )


def run_plan_generation(
    profile: dict[str, Any],
    *,
    user_request: str | None = None,
    datapack: dict[str, Any] | None = None,
    settings: Settings | None = None,
    use_demo: bool = False,
) -> dict[str, Any]:
    """生成计划 dict（含 plan_id/created_at）。失败或 use_demo 时回落设计稿示例。

    datapack：§3.2 预装包（档案 + 摘要卡 + 诉求）；有则整包喂模型，无则仅档案+诉求。
    """
    settings = settings or load_settings()
    selected_template_id = "swim_plan_v1"
    selection_meta: dict[str, Any] = {}
    if use_demo:
        body = design_demo_plan()
        selected_template_id = "design_demo"
        selection_meta = {"skill": "arena-plan", "fallback": "design_demo"}
    else:
        try:
            from src.advice_datapack import datapack_prompt_blob

            pack = datapack if isinstance(datapack, dict) else None
            if pack is None:
                pack = {
                    "profile": profile,
                    "user_request": user_request or "按当前目标给一节常规课",
                    "summary_cards": {"sessions": [], "trends": []},
                    "headlines": [],
                }
            req = user_request or str(pack.get("user_request") or "") or None
            tid, goal_bucket, level = select_template_id(
                profile or pack.get("profile") or {},
                user_request=req,
                datapack=pack,
            )
            seed = load_template(tid)
            selected_template_id = tid
            selection_meta = {
                "goal_bucket": goal_bucket,
                "level": level,
                "template_id": tid,
                "theme": seed.get("theme"),
                "duration_min": seed.get("duration_min"),
                "skill": "arena-plan",
            }
            # volume_m 取区间中点供概览页兜底
            try:
                band = seed.get("volume_band_m") or []
                selection_meta["volume_m"] = int(round((float(band[0]) + float(band[1])) / 2))
            except (TypeError, ValueError, IndexError):
                pass
            payload_text = datapack_prompt_blob(pack) if datapack else json.dumps(pack, ensure_ascii=False)
            agent = create_plan_agent(settings)
            result = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": build_plan_user_content(
                                payload_text,
                                seed,
                                goal_bucket=goal_bucket,
                                level=level,
                            ),
                        }
                    ]
                }
            )
            report = result.get("structured_response")
            if report is None:
                raise RuntimeError("计划未返回 structured_response")
            body = report.model_dump() if isinstance(report, BaseModel) else dict(report)
            # 模型常把 equipment 漏成 null；按种子同序回填器材/类型
            body["sections"] = merge_seed_section_fields(
                list(body.get("sections") or []),
                list(seed.get("sections") or []),
            )
        except Exception as exc:
            _LOGGER.exception("plan generation failed; fallback design demo")
            try:
                Path("/tmp/plan_agent_last_error.txt").write_text(
                    f"{type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            body = design_demo_plan()
            selected_template_id = "design_demo"
            selection_meta = {
                "skill": "arena-plan",
                "fallback": "design_demo",
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }

    now = datetime.now(timezone.utc).isoformat()
    meta = (datapack or {}).get("meta") if isinstance(datapack, dict) else None
    based_on: dict[str, Any] = {}
    if isinstance(meta, dict):
        based_on.update(meta)
    based_on.update(selection_meta)
    # 按档案泳池对齐距离（Arena 种子默认 25m 单位）
    prof = profile or {}
    if isinstance(datapack, dict) and not (
        prof.get("pool_length_m") or prof.get("pool_length")
    ):
        pack_prof = datapack.get("profile") if isinstance(datapack.get("profile"), dict) else {}
        prof = {**pack_prof, **prof}
    pool = prof.get("pool_length_m") or prof.get("pool_length")
    sections = align_sections_to_pool(list(body.get("sections") or []), pool)
    if _coerce_pool_m(pool) is not None:
        based_on["pool_length_m"] = _coerce_pool_m(pool)
        based_on["pool_aligned"] = True
    return {
        "plan_id": str(uuid.uuid4()),
        "created_at": now,
        "template_id": selected_template_id,
        "sections": sections,
        "based_on": based_on,
    }


def format_rest(rest_s: int | None) -> str | None:
    """休息秒 → 0:15。"""
    if rest_s is None:
        return None
    m, s = divmod(int(rest_s), 60)
    return f"{m}:{s:02d}"


def section_to_metrics(section: dict[str, Any]) -> list[dict[str, str]]:
    """板块 → 表盘 metrics 行。顺序：距离→泳姿→类型→器材→次数→注释→休息；空值整行省略。"""
    rows: list[dict[str, str]] = []
    dist = section.get("distance_m")
    if dist is not None:
        rows.append({"label": "距离", "value": f"{int(round(float(dist)))}米"})
    stroke = section.get("stroke")
    if stroke:
        rows.append({"label": "泳姿", "value": str(stroke)})
    drill = section.get("drill_type")
    if drill:
        rows.append({"label": "类型", "value": str(drill)})
    equip = section.get("equipment")
    if equip:
        rows.append({"label": "器材", "value": str(equip)})
    # 主项用 Part 区分后，次数改进行内，不再用标题角标「N次」
    repeat = section.get("repeat")
    try:
        if repeat is not None and int(repeat) > 1:
            rows.append({"label": "次数", "value": f"{int(repeat)}次"})
    except (TypeError, ValueError):
        pass
    note = section.get("note")
    if note:
        rows.append({"label": "注释", "value": str(note)})
    rest = format_rest(section.get("rest_s"))
    if rest:
        rows.append({"label": "休息", "value": rest})
    return rows


def merge_seed_section_fields(
    sections: list[dict[str, Any]],
    seed_sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按序把种子课里的器材/类型回填到模型漏掉的 null 字段（不覆盖模型已填值）。"""
    out: list[dict[str, Any]] = []
    for i, sec in enumerate(sections):
        row = dict(sec)
        if i < len(seed_sections):
            src = seed_sections[i] or {}
            if not row.get("equipment") and src.get("equipment"):
                row["equipment"] = src["equipment"]
            if not row.get("drill_type") and src.get("drill_type"):
                row["drill_type"] = src["drill_type"]
        out.append(row)
    return fill_equipment_hints(out)


# Arena 模板默认按短池 25 米写距离与注释（25/50/100…）
_TEMPLATE_POOL_M = 25.0


def _coerce_pool_m(pool: Any) -> float | None:
    """档案泳池长度 → 正浮点米；无效则 None。"""
    if pool is None or pool == "":
        return None
    try:
        val = float(pool)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def snap_distance_to_pool(distance_m: float, pool_m: float) -> float:
    """把距离收成整趟泳池长度（至少 1 趟）。"""
    n = max(1, int(round(float(distance_m) / float(pool_m))))
    return float(n * pool_m)


def rewrite_meters_for_pool(
    text: str,
    pool_m: float,
    *,
    template_pool_m: float = _TEMPLATE_POOL_M,
) -> str:
    """把注释里按模板池长写的「N米」改成运动员池长单位。

    仅改写 0.5/1/1.5/2… 倍模板池长的数字（如 25、50、100）；
    奇数米数保持原样。标准长池(50)不改写注释（25 常表示半趟）。
    """
    if not text or abs(pool_m - template_pool_m) < 0.01:
        return text
    if abs(pool_m - 50.0) < 0.01:
        return text
    half = template_pool_m / 2.0

    def _repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        try:
            val = float(raw)
        except ValueError:
            return match.group(0)
        half_units = val / half
        if abs(half_units - round(half_units)) > 0.08:
            return match.group(0)
        new_val = (val / template_pool_m) * pool_m
        if abs(new_val - round(new_val)) < 0.05:
            shown = str(int(round(new_val)))
        else:
            shown = f"{new_val:.1f}".rstrip("0").rstrip(".")
        return f"{shown}米"

    return re.sub(r"(\d+(?:\.\d+)?)\s*米", _repl, text)


def align_sections_to_pool(
    sections: list[dict[str, Any]],
    pool_m: Any,
    *,
    template_pool_m: float = _TEMPLATE_POOL_M,
) -> list[dict[str, Any]]:
    """按运动员泳池长度对齐板块距离与注释中的米数（SKILL §6）。"""
    pool = _coerce_pool_m(pool_m)
    if pool is None or not sections:
        return sections
    out: list[dict[str, Any]] = []
    for sec in sections:
        row = dict(sec)
        dist = row.get("distance_m")
        if dist is not None:
            try:
                row["distance_m"] = snap_distance_to_pool(float(dist), pool)
            except (TypeError, ValueError):
                pass
        note = row.get("note")
        if isinstance(note, str) and note.strip():
            row["note"] = rewrite_meters_for_pool(
                note, pool, template_pool_m=template_pool_m
            )
        out.append(row)
    return out


def normalize_equipment_name(equip: str | None) -> str | None:
    """统一器材显示名；旧计划「夹水器」→「8字板」。"""
    if not equip:
        return None
    name = str(equip).strip()
    if name in ("夹水器", "夹水板", "pull buoy", "pullbuoy", "Pull buoy"):
        return "8字板"
    return name


def fill_equipment_hints(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """种子/模型未给器材时，按类型与注释推断常用器材（可上屏「器材」行）。"""
    out: list[dict[str, Any]] = []
    for sec in sections:
        row = dict(sec)
        if row.get("equipment"):
            row["equipment"] = normalize_equipment_name(str(row["equipment"]))
            out.append(row)
            continue
        note = str(row.get("note") or "")
        drill = str(row.get("drill_type") or "")
        blob = f"{note} {drill}"
        equip: str | None = None
        if re.search(r"呼吸管|snorkel", blob, re.I):
            equip = "呼吸管"
        elif re.search(r"手蹼|paddle", blob, re.I):
            equip = "手蹼"
        elif re.search(r"脚蹼|fins?", blob, re.I):
            equip = "脚蹼"
        elif re.search(r"8字板|夹水|pull.?buoy", blob, re.I):
            equip = "8字板"
        elif re.search(r"浮板|kickboard", blob, re.I):
            equip = "浮板"
        elif drill == "踢动" or re.search(r"打腿|双腿|仅腿|腿部", blob):
            equip = "浮板"
        elif drill == "划水" or re.search(r"双臂|仅臂|划臂|拉水", blob):
            equip = "8字板"
        if equip:
            row["equipment"] = equip
        out.append(row)
    return out


def plan_total_distance_m(sections: list[dict[str, Any]]) -> int:
    """课表总距离（米）= Σ distance_m × repeat。"""
    total = 0.0
    for sec in sections:
        try:
            dist = float(sec.get("distance_m") or 0)
            rep = int(sec.get("repeat") or 1)
        except (TypeError, ValueError):
            continue
        total += dist * max(rep, 1)
    return int(round(total))


_LEVEL_CN = {"easy": "简单", "medium": "中等", "hard": "较难"}
_GOAL_CN = {
    "learn": "学习技术",
    "technique": "提高技巧",
    "endurance": "耐力有氧",
    "speed": "速度",
    "tone": "塑形燃脂",
    "wellbeing": "健康放松",
}


def _overview_goal_text(theme: str, bucket: str) -> str:
    """表盘概览区约 4 行窄列：目标过长会换行顶掉距离/耗时/难度，必须短。"""
    bucket_cn = _GOAL_CN.get(bucket) or ""
    t = (theme or "").strip()
    for sep in (" - ", " — ", " – ", "－", "（", "(", "：", ":", "！", "!", "，", ","):
        if sep in t:
            head = t.split(sep, 1)[0].strip()
            if head:
                t = head
                break
    if t and len(t) <= 8:
        return t
    if bucket_cn:
        return bucket_cn
    if t:
        return t[:7] + "…"
    return "常规训练"


def build_overview_page(plan: dict[str, Any]) -> dict[str, Any]:
    """计划首页：目标 / 距离 / 耗时 / 难度（四行短值，保证一屏可见）。"""
    based = plan.get("based_on") if isinstance(plan.get("based_on"), dict) else {}
    sections = plan.get("sections") or []
    theme = str(based.get("theme") or plan.get("theme") or "").strip()
    bucket = str(based.get("goal_bucket") or "")
    goal = _overview_goal_text(theme, bucket)
    level = str(based.get("level") or plan.get("level") or "")
    level_cn = _LEVEL_CN.get(level, level or "中等")
    duration = based.get("duration_min")
    if duration is None:
        duration = plan.get("duration_min")
    try:
        duration_i = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_i = None
    dist = plan_total_distance_m(list(sections))
    if dist <= 0:
        try:
            dist = int(round(float(based.get("volume_m") or 0)))
        except (TypeError, ValueError):
            dist = 0
    # 固定四行顺序，缺项也给占位，避免只剩「目标」一行显得信息不全
    metrics: list[dict[str, str]] = [
        {"label": "目标", "value": goal},
        {"label": "距离", "value": f"{dist}米" if dist > 0 else "—"},
        {"label": "耗时", "value": f"{duration_i}分钟" if duration_i and duration_i > 0 else "—"},
        {"label": "难度", "value": level_cn},
    ]
    return {"title": "概览", "repeat_badge": "", "metrics": metrics}


def plan_to_ui_pages(
    plan: dict[str, Any],
    *,
    pool_length_m: Any = None,
) -> list[dict[str, Any]]:
    """计划 → 翻页单元。

    首页为「概览」（目标/距离/耗时/难度）；其后多个「主要」标 Part1/Part2/…
    （标题形如「主要      Part1」）；竖条由固件绘制。不再用「N次」角标区分主项。
    pool_length_m：展示时按当前档案泳池对齐旧计划（未对齐入库的也可纠正）。
    """
    # 展示前再补一次器材推断，兼容库里旧计划漏 null 的情况
    plan_view = dict(plan)
    sections = list(plan.get("sections") or [])
    pool = pool_length_m
    if pool is None:
        based = plan.get("based_on") if isinstance(plan.get("based_on"), dict) else {}
        pool = based.get("pool_length_m")
    sections = align_sections_to_pool(sections, pool)
    plan_view["sections"] = fill_equipment_hints(sections)
    pages: list[dict[str, Any]] = [build_overview_page(plan_view)]
    sections = plan_view["sections"]
    main_total = sum(1 for s in sections if (s.get("kind") or "main") == "main")
    main_ord = 0
    for section in sections:
        kind = section.get("kind") or "main"
        base = KIND_TITLE.get(str(kind), str(kind))
        if kind == "main" and main_total > 1:
            main_ord += 1
            # 竖条由 UI 画；标题内空格拉开「主要」与 Part
            title = f"{base}      Part{main_ord}"
            badge = ""
        else:
            title = base
            # 非主项若仍有 repeat，保留角标（主项次数已进 metrics）
            repeat = section.get("repeat")
            try:
                badge = f"{int(repeat)}次" if repeat is not None and int(repeat) > 1 else ""
            except (TypeError, ValueError):
                badge = ""
        metrics = section_to_metrics(section)
        # 注释/休息单独续页；其余每屏最多 3 行，避免长文换行把后面字段顶出屏且无法下翻
        head = [m for m in metrics if m["label"] not in ("注释", "休息")]
        tail = [m for m in metrics if m["label"] in ("注释", "休息")]
        if not head and not tail:
            continue
        if head:
            for i in range(0, len(head), 3):
                pages.append(
                    {
                        "title": title,
                        "repeat_badge": badge,
                        "metrics": head[i : i + 3],
                    }
                )
        for item in tail:
            value = str(item.get("value") or "")
            if item.get("label") == "注释" and value:
                # 窄列约 2 行可见；整段一页会被裁切且下页跳到「休息」丢字
                # 注释改为上下通栏排版后，单页可容纳更多字
                for chunk in _chunk_plan_note(value, max_chars=36):
                    pages.append(
                        {
                            "title": title,
                            "repeat_badge": badge,
                            "metrics": [{"label": "注释", "value": chunk}],
                        }
                    )
            else:
                pages.append(
                    {
                        "title": title,
                        "repeat_badge": badge,
                        "metrics": [item],
                    }
                )
    return pages


def _chunk_plan_note(text: str, *, max_chars: int = 18) -> list[str]:
    """把计划注释拆成墨水屏单页放得下的短段；尽量在标点处断开。"""
    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    breaks = set("；;。！？，、, ")
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            window = text[start:end]
            # 后半段找最近标点，避免「后」字被裁在页末
            cut = -1
            for i in range(len(window) - 1, max(len(window) // 3, 0), -1):
                if window[i] in breaks:
                    cut = i + 1
                    break
            if cut > 0:
                end = start + cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks or [text]


def profile_summary_text(profile: dict[str, Any] | None) -> str:
    """档案摘要文案（设计稿 NAKaD/OVLGN 中部）。"""
    if not profile:
        return ""
    parts: list[str] = []
    sex = profile.get("sex") or profile.get("gender")
    if sex in ("男", "male", "M", "m"):
        parts.append("男性用户")
    elif sex in ("女", "female", "F", "f"):
        parts.append("女性用户")
    age = profile.get("age")
    if age is not None:
        parts.append(f"年纪{age}岁")
    height = profile.get("height_cm") or profile.get("height")
    if height is not None:
        parts.append(f"身高{int(height)}cm")
    weight = profile.get("weight_kg") or profile.get("weight")
    if weight is not None:
        parts.append(f"体重{weight}kg")
    pool = profile.get("pool_length_m") or profile.get("pool_length")
    if pool is not None:
        parts.append(f"泳池{int(pool)}米")
    goal = profile.get("goal") or profile.get("training_goal")
    if goal:
        parts.append(f"训练目标：{goal}")
    pref = str(profile.get("difficulty_pref") or "").strip().lower()
    pref_cn = {"easy": "简单", "medium": "中等", "hard": "较难"}.get(pref)
    if pref_cn:
        parts.append(f"训练难度：{pref_cn}")
    return "，".join(parts)
