# 档案 / 摘要卡取法

出计划 **不写 SQL**。Worker / API 预装 Data pack 后注入 Agent。只读包内字段；缺数按 SKILL 保守规则，禁止臆造成绩。

## 装包入口

| 调用方 | 代码 / API |
|--------|------------|
| 出计划 Worker | `advice_queue._run_plan_job` → `build_advice_datapack(repo, profile)` |
| HTTP | `GET /advice/datapack?user_request=` |
| 函数 | `src.advice_datapack.build_advice_datapack` |

```text
datapack = {
  profile, user_request, headlines,
  summary_cards: { sessions: [...], trends: [...] },
  meta: { session_card_count, trend_card_count, source }
}
```

压缩进模型：`datapack_prompt_blob(datapack)`。

## 档案

| 字段 | 取法 |
|------|------|
| age / sex / height_cm / weight_kg / goal / pool_length_m | `SwimRepository.get_profile(athlete_id)` |
| 语音补全 | `advice_queue.extract_profile_slots` → 落盘 |
| HTTP | `GET /advice/profile` |

选型优先：`goal` + `pool_length_m` + `age`。

## 单次摘要卡 `summary_cards.sessions[]`

`build_session_summary_cards` ← `list_sessions_for_ui` + `get_session_report` → `session_report_to_card`

| 字段 | 调课用途 |
|------|----------|
| `metrics.distance_m` | 总课量 ≈ 上场 × [0.6, 1.3] |
| `metrics.pace_text` / `swolf` | note 提示；高 SWOLF → 技术或加 rest |
| `endurance_note` / `next_step` | 后程掉速 → 拆间歇、加 rest |
| `efficiency_note` | 技术加权 |

## 趋势摘要卡 `summary_cards.trends[]`

`build_trend_summary_cards` ← `get_trend_report` → `trend_report_to_card`（默认 1W / 1M / 3M）

| 字段 | 调课用途 |
|------|----------|
| `load_note` | 负荷高 → 降档 / wellbeing |
| `progress_note` | 可略增 volume |
| `sample_insufficient` | Easy + band 下限 |

## 计划输出侧

`plan_agent.run_plan_generation` → `_save_plan`；`GET /advice/plan`、`POST /advice/plan/analyze`。返回须带 `template_id`。

## 不做

不调用 SQL Agent；不在 plan Agent 内现算五主题；不用原始 Garmin 表行。无摘要时仅用档案 + 模板 `volume_band_m` 下限。
