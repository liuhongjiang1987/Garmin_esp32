# Swim Analysis Agents（2.0）

## 产品时序

### 单次分析（预计算）

```text
每天定时同步 Garmin → 写入 swim_evidence
  → after-sync：新场次入队 status=analyzing（列表转圈）
  → Worker 跑 session Agent → 报告入库 ✓
  → 表盘点 ✓ → GET .../report（只读）
```

### 趋势分析（点选触发 + 结果缓存）

```text
九宫格点「1个月」等
  → POST /trends/{span}/analyze
     · cached=true → 直接 GET .../report（不跑模型）
     · 否则入队 → 「分析中」页轮询 status → report
成功报告按跨度保存；窗口场次未变则复用。
after-sync 仅在有新场次时作废趋势缓存（不同步预跑九档）
```

| 文件 | 职责 |
|------|------|
| `src/session_analysis_agent.py` | 单次 Agent |
| `src/trend_analysis_agent.py` | 趋势 Agent（报告含 `charts.swolf/pace/distance`） |
| `src/analysis_queue.py` | 入队 / 处理 / 列表；趋势 `request_trend_analysis` |
| `src/api.py` | 表盘 API + `/internal/after-sync` |

## 常用命令

```bash
cd agent

# 同步后（只消化单次；作废趋势缓存）
python -m src.cli after-sync

# 单次列表
python -m src.cli list-sessions
python -m src.cli show-report --activity-id 638297383

# 趋势：模拟点选 → 可选立刻跑完 → 轮询 / 读报告
python -m src.cli list-trends
python -m src.cli request-trend --span 1m --run
python -m src.cli trend-status --span 1m
python -m src.cli show-trend-report --span 1m

# 继续消化队列（含用户已点选的趋势）
python -m src.cli process-jobs

# HTTP
python -m src.cli serve
# GET  /sessions  /sessions/{id}/report
# GET  /trends
# POST /trends/{span}/analyze
# GET  /trends/{span}/status
# GET  /trends/{span}/report
# POST /internal/after-sync
```

`analyze-session` / `analyze-trend` 仅 **DEBUG**（绕过队列直接调模型）。

## 和 NAS 同步衔接

```bash
../scripts/after_sync_analyze.sh
# 或 curl -X POST http://127.0.0.1:8765/internal/after-sync
```
