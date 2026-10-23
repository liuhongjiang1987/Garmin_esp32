# 开发说明

## 当前数据

- 活动库：`../data/garmindb_fixtures/garmin_activities.db`，只有 `activities`，由 CSV 重建
- 健康库：`../data/garmindb_fixtures/garmin.db`，保留，当前教练不查询
- 教练库：`./data/coach.db`，evidence、单圈、档案和主观笔记
- 查询缓存：`./data/swim_sql.db`，每次 `ask_swim_database` 前重建，可以删除

活动唯一来源是 `data/activity_*.csv`。重建：

```bash
python3 ../scripts/build_fixtures_from_csv.py
```

## 对话

```bash
python -m src.cli chat
```

模型、接口和库路径来自 `agent/.env`，由 `src/config.py` 读取。

## 代码入口

- `src/cli.py`：`init`、`analytics`、`chat`、`validate`
- `src/coach_agent.py`：Deep Agents 主教练、短系统提示、流式输出（Skills 按需加载）
- `src/sql_agent.py`：薄 SQL 子代理（固定两视图 + 安全门）
- `skills/swim-coach/`：主循环 + references（回合预算 / 意图 / 可查口径 / 口语 / 主题卡）
- `src/tools.py`：档案和采访工具
- `src/analytics/pipeline.py`：把一场 CSV 算成 evidence 并落库

## 尚未接入

- FastAPI 与 ESP32
- `garmin.db` 里的体重、静息心率和每日摘要
