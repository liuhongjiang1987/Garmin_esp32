# 开发说明（2.0）

## 数据

- 活动库：`../data/garmindb_fixtures/garmin_activities.db`
- 教练库：`./data/coach.db`（evidence、单圈增强、档案）
- NAS 证据库（若挂载）：`SWIM_EVIDENCE_DB` / 默认 `/Volumes/home/.../swim_evidence.db`

活动样例 CSV 重建：

```bash
python3 ../scripts/build_fixtures_from_csv.py
```

## 分析入口（队列）

```bash
python -m src.cli init
python -m src.cli after-sync          # 同步后：入队 + 处理
python -m src.cli list-sessions       # 表盘列表状态
python -m src.cli show-report --activity-id ID   # 只读报告
python -m src.cli process-jobs        # 继续消化队列
```

模型与路径来自 `agent/.env`（`src/config.py`）。

## 代码

| 路径 | 说明 |
|------|------|
| `src/analysis_queue.py` | 入队 / Worker / 列表只读 |
| `src/session_analysis_agent.py` | 单次 Agent |
| `src/trend_analysis_agent.py` | 趋势 Agent |
| `src/repository/swim_repo.py` | SQLite 访问 |
| `src/cli.py` / `src/api.py` | CLI 与 HTTP |

已删除：`coach_agent.py`、`sql_agent.py`、`tools.py`、`speech.py`、`skills/swim-coach/`。

## 综合建议

出计划 / 薄对话尚未在本包落地；见 `docs/2.0/`。
