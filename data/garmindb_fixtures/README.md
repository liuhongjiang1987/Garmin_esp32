# GarminDB 开发 Fixture

活动库由 `scripts/build_fixtures_from_csv.py` 以 `data/` 下的 Garmin 导出泳池 CSV 为唯一数据源从零重建。

## 文件

| 文件 | 对应 GarminDB | 说明 |
| --- | --- | --- |
| `garmin_activities.db` | 活动库：仅 `activities` 表 | 由 CSV 构建脚本重建。SQL 子代理用它补活动开始时间 |
| `garmin.db` | 健康库：`attributes` / `devices` / `files` / `weight` / `resting_hr` / `daily_summary` | 保留，供未来负荷/体重/静息心率分析；当前 agent 未查询 |
| `FitFiles/` | 原始 FIT 副本 | 历史遗留，当前流程不使用 |

## 样例活动（均来自 CSV，模拟 start_time）

| activity_id | 来源 CSV | 模拟日期 | 说明 |
| --- | --- | --- | --- |
| `629742595` | `data/activity_629742595.csv` | 2026-07-24 | 泳池游泳 2.04km |
| `635801116` | `data/activity_635801116.csv` | 2026-08-21 | 泳池游泳 1.59km |
| `638297383` | `data/activity_638297383.csv` | 2026-09-11 | 泳池游泳 1.02km（最新一场） |

## 单位约定（fixture）

- `distance`：千米（由 CSV 米值 / 1000）
- `avg_speed`：km/h（由总距离/总时长换算）
- `elapsed_time` / `moving_time`：`HH:MM:SS` 文本
- 枚举列存 TEXT（如 `sport='swimming'`）

## 重建方式

```bash
python3 scripts/build_fixtures_from_csv.py
```

该脚本会从零重建 `garmin_activities.db` 的 `activities` 表，并在 `coach.db` 落 evidence / swim_lengths / swim_laps_enriched。

## 明确不包含

- 不再使用 FIT/TCX 解析流程；活动库仅 `activities` 一张表
- 无 `activity_laps` / `activity_records` / `activities_devices`（已移除，agent 未使用）
- 无 `activity_lengths`、无完整 monitoring / summary 库
- 非 GarminDB 运行时产物，勿当作 Connect 同步结果备份
