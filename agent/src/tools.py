# 模块级说明：定义主教练可调用的档案与采访工具。训练数字不在这里查，由 SQL 子代理负责。

from __future__ import annotations

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

        Args:
            age: 年龄。
            gender: 性别。
            height_cm: 身高，单位厘米。
            weight_kg: 体重，单位千克。
            weekly_sessions: 每周可训练次数。
            goal: 训练目标。
            typical_pool_length_m: 常用泳池长度，单位米。
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

    # 逐行注释：知识卡不在这里。模型用 read_file 读取技能 references。
    return [
        query_athlete_state,
        assess_readiness,
        save_profile_fields,
        save_subjective_note,
    ]
