# 模块级说明：定义主教练可调用的档案、采访和 CSS 工具。训练数字不在这里查，由 SQL 子代理负责。

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from langchain.tools import tool

from src.repository.swim_repo import SwimRepository

# 逐行注释：主题 ID 到中文名的映射，供工具对外返回可读主题名。
TOPIC_NAMES = {
    "efficiency": "游泳效率分析",
    "endurance_fatigue": "有氧耐力与疲劳漂移分析",
    "stability_asymmetry": "动作稳定性与不对称风险分析",
    "load_risk": "训练负荷与过度疲劳风险分析",
    "trend_progress": "训练周期与进步趋势分析",
}

# 逐行注释：各主题分析所需的主观信息（语义化描述 + 建议问法），用于充分性评估。
TOPIC_SUBJECTIVE_NEEDS = {
    "efficiency": [
        {"key": "本次训练意图", "question": "这次是刻意放慢打磨技术，还是尽力游？"},
        {"key": "换气感受", "question": "换气时紧张吗，有没有憋气的情况？"},
        {"key": "单侧发力", "question": "有没有感觉某一侧肩背更吃力？"},
    ],
    "endurance_fatigue": [
        {"key": "主观疲劳", "question": "这次训练主观上有多累（1到10分）？"},
        {"key": "睡眠精力", "question": "最近睡眠和当天精力怎么样？"},
        {"key": "后半程体感", "question": "后半程体感是可控疲劳，还是明显顶不住？"},
    ],
    "stability_asymmetry": [
        {"key": "单侧不适", "question": "有没有单侧更吃力或不适的感觉？"},
        {"key": "呼吸偏侧", "question": "你平时主要单侧换气还是双侧换气？"},
        {"key": "后程动作", "question": "后半程动作是不是更容易变散？"},
    ],
    "load_risk": [
        {"key": "延迟疲劳", "question": "训练后第二天恢复感如何？"},
        {"key": "疼痛不适", "question": "最近有没有持续几天的疼痛或不适？"},
        {"key": "睡眠压力", "question": "最近睡眠、补水和生活压力怎么样？"},
    ],
    "trend_progress": [
        {"key": "目标达成", "question": "最近这几周训练目标达成感如何？"},
        {"key": "可持续性", "question": "目前的训练频次你能长期坚持吗？"},
        {"key": "动力变化", "question": "最近训练动力是上升、稳定还是下降？"},
    ],
}

def build_tools(repo: SwimRepository):
    """构建档案、采访和保存工具。训练数据工具在创建教练时另行挂上。"""
    profile_required_fields = {
        "age": "年龄",
        "gender": "性别",
        "height_cm": "身高（cm）",
        "weight_kg": "体重（kg）",
    }
    profile_high_value_fields = {
        "weekly_sessions": "每周可训练次数",
        "goal": "训练目标",
        "typical_pool_length_m": "常用泳池长度（米）",
    }

    def _build_state_gaps(profile: dict[str, Any] | None) -> list[dict[str, str]]:
        """生成状态缺口列表。"""
        data = profile or {}
        gaps: list[dict[str, str]] = []
        for key, label in profile_required_fields.items():
            value = data.get(key)
            if value in (None, "", 0):
                gaps.append({"field": key, "label": label, "priority": "required"})
        for key, label in profile_high_value_fields.items():
            value = data.get(key)
            if value in (None, "", 0):
                gaps.append({"field": key, "label": label, "priority": "high_value"})
        return gaps

    @tool(parse_docstring=True)
    def query_athlete_state() -> dict[str, Any]:
        """查询运动员长期状态 JSON，包含档案、滚动表现、最近主观笔记和档案缺口。

        准备给训练建议，或判断要不要采访时调用。纯查询训练数字时不必调用。短期对话不用这个工具。

        Args:
        """
        # 逐行注释：读取档案；没有档案时给空对象。
        profile = repo.get_profile("default") or {}
        # 逐行注释：读取滚动表现，并去掉内部标签，避免模型把标签说给用户。
        performance = dict(repo.get_performance_state("default") or {})
        performance.pop("latest_labels", None)
        # 逐行注释：读取最近主观笔记。
        notes = repo.list_subjective_notes("default", limit=8)
        # 逐行注释：计算尚未填写的档案项。
        gaps = _build_state_gaps(profile)
        return {
            "ok": True,
            "profile": profile,
            "performance_state": performance,
            "recent_subjective": notes,
            "profile_gaps": gaps,
        }

    @tool(parse_docstring=True)
    def save_subjective_note(
        activity_id: str | None = None,
        rpe: int | None = None,
        fatigue_note: str | None = None,
        pain_note: str | None = None,
        feel_note: str | None = None,
    ) -> dict[str, Any]:
        """把用户说出的主观训练感受写入长期状态。

        Args:
            activity_id: 对应的活动 id。不知道就留空。
            rpe: 主观疲劳分，1 到 10。用户没给就留空。
            fatigue_note: 疲劳或睡眠相关的原话摘要。
            pain_note: 疼痛或不适的原话摘要。
            feel_note: 其他体感的原话摘要。
        """
        # 逐行注释：调用仓库层插入 subjective_memory。
        repo.add_subjective_note(
            athlete_id="default",
            activity_id=activity_id,
            rpe=rpe,
            fatigue_note=fatigue_note,
            pain_note=pain_note,
            feel_note=feel_note,
        )
        # 逐行注释：返回成功状态，供 Agent 明确反馈。
        return {"ok": True, "saved": True}

    @tool(parse_docstring=True)
    def save_profile_fields(
        age: int | None = None,
        gender: str | None = None,
        height_cm: float | None = None,
        weight_kg: float | None = None,
        weekly_sessions: int | None = None,
        goal: str | None = None,
        typical_pool_length_m: float | None = None,
        blood_pressure_systolic: int | None = None,
        blood_pressure_diastolic: int | None = None,
        injury_notes: str | None = None,
    ) -> dict[str, Any]:
        """更新运动员档案里本次新提供的字段，未传入的字段保持原值。

        用户说出或更正泳池长度、周次、目标、年龄等时必须调用，不要只口头确认。

        Args:
            age: 年龄。
            gender: 性别。
            height_cm: 身高，单位厘米。
            weight_kg: 体重，单位千克。
            weekly_sessions: 每周可训练次数。
            goal: 训练目标。
            typical_pool_length_m: 常用泳池长度，单位米。用户说 25 米池、30 米池、50 米池时写入对应数字。
            blood_pressure_systolic: 收缩压。
            blood_pressure_diastolic: 舒张压。
            injury_notes: 伤病或限制说明。
        """
        # 逐行注释：先读现有档案，再只覆盖非空字段。
        current = repo.get_profile("default") or {"athlete_id": "default"}
        patch = {
            "age": age,
            "gender": gender,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "weekly_sessions": weekly_sessions,
            "goal": goal,
            "typical_pool_length_m": typical_pool_length_m,
            "blood_pressure_systolic": blood_pressure_systolic,
            "blood_pressure_diastolic": blood_pressure_diastolic,
            "injury_notes": injury_notes,
        }
        updated_keys: list[str] = []
        for key, value in patch.items():
            if value is not None:
                current[key] = value
                updated_keys.append(key)
        repo.upsert_profile("default", current)
        gaps = _build_state_gaps(current)
        return {
            "ok": True,
            "updated_keys": updated_keys,
            "remaining_required_gaps": [item for item in gaps if item["priority"] == "required"],
        }

    @tool(parse_docstring=True)
    def assess_readiness(topic: str, activity_id: str = "latest") -> dict[str, Any]:
        """评估某个分析主题还缺哪些主观信息，并给出建议问法。

        只提供判断依据。是否采访、怎么问，由你决定。训练数字请先用 ask_swim_database 获取。

        Args:
            topic: 主题。取值为 efficiency、endurance_fatigue、stability_asymmetry、load_risk、trend_progress。
            activity_id: 传 latest，或传查询工具已返回的 activity_id。
        """
        # 逐行注释：解析目标活动 id。
        target_activity_id = activity_id
        if activity_id == "latest":
            latest = repo.get_latest_swim_activity_id()
            if latest is None:
                return {"ok": False, "reason": "no_swim_activity_found"}
            target_activity_id = latest
        # 逐行注释：判断客观 evidence 是否已就绪。
        evidence = repo.get_evidence(target_activity_id)
        has_objective_data = bool(evidence)
        # 逐行注释：读取 profile，用于基础档案缺口判断。
        profile = repo.get_profile("default") or {}
        profile_gaps = _build_state_gaps(profile)
        # 逐行注释：取该主题所需主观信息清单。
        subjective_needs = TOPIC_SUBJECTIVE_NEEDS.get(topic, [])
        missing_subjective = [item["key"] for item in subjective_needs]
        suggested_questions = [item["question"] for item in subjective_needs]
        # 逐行注释：若档案缺必填项，把第一条放在建议问法最前。
        if profile_gaps:
            suggested_questions = [
                f"为了建议更准确，先补充一下你的{profile_gaps[0]['label']}。"
            ] + suggested_questions
        return {
            "ok": True,
            "topic": topic,
            "topic_name": TOPIC_NAMES.get(topic, topic),
            "activity_id": target_activity_id,
            "has_objective_data": has_objective_data,
            "missing_subjective": missing_subjective,
            "profile_gaps": [item["label"] for item in profile_gaps],
            "suggested_questions": suggested_questions,
            "ready_to_answer": has_objective_data,
        }

    # ── CSS 锚点工具 ──

    def _pace_text(seconds: float) -> str:
        """把秒/100米写成可直接念的分秒。"""
        total = int(round(seconds))
        return f"{total // 60}分{total % 60:02d}秒/100米"

    def _build_zones(css_s: float) -> dict[str, Any]:
        """根据 CSS 秒/100米计算五个训练区的配速范围。"""
        # 逐行注释：默认秒差来自专家建议，不是医疗处方，可按体感微调。
        return {
            "Z1_有氧恢复": {"slow": _pace_text(css_s + 25), "fast": _pace_text(css_s + 15), "desc": "轻松放松，比 CSS 慢 15~25 秒"},
            "Z2_有氧技术": {"slow": _pace_text(css_s + 15), "fast": _pace_text(css_s + 8), "desc": "稳定有氧，比 CSS 慢 8~15 秒"},
            "Z3_阈值": {"slow": _pace_text(css_s + 2), "fast": _pace_text(css_s - 2), "desc": "接近 CSS，正负 2 秒"},
            "Z4_短距质量": {"slow": _pace_text(css_s - 3), "fast": _pace_text(css_s - 8), "desc": "比 CSS 快 3~8 秒"},
            "Z5_冲刺": {"slow": _pace_text(css_s - 8), "fast": "", "desc": "全力冲刺，短距离"},
        }

    @tool(parse_docstring=True)
    def save_css_anchor(
        css_seconds_per_100m: float,
        test_method: str,
        source: str = "自测",
        test_date: str | None = None,
        retest_weeks: int = 6,
        note: str | None = None,
    ) -> dict[str, Any]:
        """保存用户的 CSS（临界游速）锚点，同时自动算出五个训练区和复测日期。

        复测后必须再次调用本工具更新锚点，区和组次会一起更新。不要只改数字不改区。

        Args:
            css_seconds_per_100m: 临界游速，秒/100米。
            test_method: 测法，例如「400+200 自测」或「自报」。
            source: 来源，取值「自测」或「自报」。标明非手表自动官方值。
            test_date: 测试日期，格式 YYYY-MM-DD。不传则用今天。
            retest_weeks: 建议复测间隔周数，默认 6。
            note: 补充说明。
        """
        # 逐行注释：解析测试日期，缺省用今天。
        dt = date.fromisoformat(test_date) if test_date else date.today()
        # 逐行注释：计算复测到期日。
        retest_due = (dt + timedelta(weeks=retest_weeks)).isoformat()
        # 逐行注释：计算五个训练区配速范围。
        zones = _build_zones(css_seconds_per_100m)
        anchor = {
            "css_seconds_per_100m": css_seconds_per_100m,
            "css_pace_text": _pace_text(css_seconds_per_100m),
            "test_method": test_method,
            "source": source,
            "test_date": dt.isoformat(),
            "retest_due": retest_due,
            "zones": zones,
            "note": note,
        }
        # 逐行注释：写入数据库，旧锚点自动标为非当前。
        repo.save_css_anchor("default", anchor)
        return {"ok": True, "anchor": anchor}

    @tool(parse_docstring=True)
    def query_css_anchor() -> dict[str, Any]:
        """查询当前生效的 CSS 锚点、训练区和复测日期。

        点名展开 CSS 或表现主题时先调用这个。没有锚点时返回提示。

        Args:
        """
        # 逐行注释：读取当前锚点。
        current = repo.get_current_css_anchor("default")
        if current is None:
            return {
                "ok": True,
                "has_anchor": False,
                "hint": "还没有 CSS 锚点。可以引导用户做一次 400+200 测试或自报一个参考配速。",
            }
        # 逐行注释：检查是否到了复测窗。
        due = current.get("retest_due", "")
        overdue = due and due <= date.today().isoformat()
        return {
            "ok": True,
            "has_anchor": True,
            "css_pace": current["css_pace_text"],
            "css_seconds": current["css_seconds_per_100m"],
            "test_method": current["test_method"],
            "source": current["source"],
            "test_date": current["test_date"],
            "retest_due": due,
            "retest_overdue": overdue,
            "zones": current["zones"],
            "note": current.get("note"),
        }

    # 逐行注释：知识卡不在这里。模型用 read_file 读取技能 references。
    return [
        query_athlete_state,
        assess_readiness,
        save_profile_fields,
        save_subjective_note,
        save_css_anchor,
        query_css_anchor,
    ]
