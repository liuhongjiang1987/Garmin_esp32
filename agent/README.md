# Swim Coach Agent

第一版游泳教练。主教练负责中文口语、采访和主题建议；训练数字由 SQL 子代理按问题查询。

- 技能：`skills/swim-coach/SKILL.md`，正文每轮写入系统提示词
- 参考卡：`skills/swim-coach/references/`，点名主题后用 `read_file` 读取一份
- 档案工具：`query_athlete_state`、`assess_readiness`、`save_profile_fields`、`save_subjective_note`
- 训练数据：`ask_swim_database`，内部是只读 SQL 子代理

## 运行

在 `agent/` 目录：

```bash
python -m src.cli chat
```

输入 `q`、`quit` 或 `exit` 结束。生成过程中按 Ctrl+C 只停止本轮。

内网文字接口，默认只监听这台电脑：

```bash
python -m src.cli serve
```

`GET /health` 返回 `{"ok": true}`。`POST /ask` 的正文是 `{"text": "最近一场配速多少"}`，回答在 `reply`。

改过代码后需要重新启动这次对话，进程不会自动加载新代码。

导入样例证据：

```bash
python -m src.cli init
```

NAS 每天同步成功后会自动计算新的游泳指标，结果在共享目录的 `HealthData/DBs/swim_evidence.db`。本机挂着该共享时，教练查询读这份库。需要手动补算时：

```bash
python scripts/compute_swim_metrics.py
```

设计说明见 `docs/游泳教练Agent设计文档.md`。
