# 模块级说明：游泳数据的 SQL 子代理。主教练交来明确的查询任务，这里只写一条 SQL，经安全门后执行，并把带分秒的结果行交回。

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.constants import TAG_NOSTREAM

from src.repository.swim_repo import SwimRepository

# 逐行注释：子代理每次提问前刷新这份只读库，里面只有游泳场次和单圈。
_QUERY_DB = Path(__file__).resolve().parents[1] / "data" / "swim_sql.db"
# 逐行注释：单次查询最多带回的行数，避免把全部圈列表交回模型。
_MAX_ROWS = 30
# 逐行注释：官方消息流见到 nostream 标签就不再把这段模型输出送进用户对话。
_QUIET = {"tags": [TAG_NOSTREAM]}


def _pace_text(seconds: Any) -> str | None:
    """把秒每 100 米写成可直接说的分秒。"""
    if seconds is None:
        return None
    total = int(round(float(seconds)))
    return f"{total // 60}分{total % 60:02d}秒/100米"


def refresh_query_db(repo: SwimRepository) -> Path:
    """从教练库和活动库复制出 SQL 子代理可以查询的两张表。"""
    # 逐行注释：NAS 上的 swim_evidence.db 有同步后自动算好的场次。没有挂载时才用本机教练库。
    from src.config import load_settings

    evidence_db = load_settings().swim_evidence_db_path or repo._db_paths.coach_db
    source = sqlite3.connect(f"file:{evidence_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    # 逐行注释：活动库只用来补没有写进证据的开始时间。容器里没有这份样例库时跳过。
    activities_db = repo._db_paths.garmin_activities_db
    if activities_db.is_file():
        source.execute("ATTACH DATABASE ? AS act", (f"file:{activities_db}?mode=ro",))
    laps = source.execute(
        """
        SELECT activity_id, lap_index, distance_m, elapsed_s, pace_per_100m_s,
               avg_hr, max_hr, total_strokes, swim_stroke_hint, swolf_derived, is_rest_lap
        FROM swim_laps_enriched
        """
    ).fetchall()
    # 逐行注释：样例活动库只有三场，而且开始时间是模拟的。真实导入把开始时间写在证据里，优先用它。
    starts = {}
    if activities_db.is_file():
        starts = {
            row["activity_id"]: row["start_time"]
            for row in source.execute(
                "SELECT activity_id, start_time FROM act.activities WHERE sport = 'swimming'"
            )
        }
    evidences = source.execute("SELECT activity_id, evidence_json FROM activity_evidence").fetchall()
    source.close()
    # 逐行注释：每次重建查询库，避免对话中途分析更新后仍查到旧表。
    if _QUERY_DB.exists():
        _QUERY_DB.unlink()
    _QUERY_DB.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(_QUERY_DB)
    target.execute(
        """
        CREATE TABLE swim_sessions (
            activity_id TEXT, start_time TEXT, distance_m REAL, avg_pace_s REAL,
            avg_pace_text TEXT, avg_swolf REAL, avg_hr REAL, max_hr REAL, total_strokes REAL,
            rest_time_s REAL, rest_ratio REAL
        )
        """
    )
    target.execute(
        """
        CREATE TABLE swim_laps (
            activity_id TEXT, lap_index INTEGER, distance_m REAL, elapsed_s REAL,
            pace_per_100m_s REAL, pace_text TEXT, avg_hr REAL, max_hr REAL,
            total_strokes REAL, swim_stroke_hint TEXT, swolf_derived REAL, is_rest_lap INTEGER
        )
        """
    )
    for row in evidences:
        evidence = json.loads(row["evidence_json"])
        level0 = evidence.get("l0") or {}
        level1 = evidence.get("l1") or {}
        pace = level1.get("avg_pace_per_100m_s")
        # 逐行注释：证据里的开始时间来自 NAS 活动库的本地时间。没有时才退回样例活动库。
        start_time = evidence.get("start_time") or starts.get(row["activity_id"])
        target.execute(
            "INSERT INTO swim_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["activity_id"],
                start_time,
                level0.get("total_distance_m"),
                pace,
                _pace_text(pace),
                level1.get("avg_swolf_derived"),
                level0.get("avg_hr"),
                level0.get("max_hr"),
                level0.get("total_strokes"),
                level1.get("rest_time_s"),
                level1.get("rest_time_ratio"),
            ),
        )
    target.executemany(
        "INSERT INTO swim_laps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                row["activity_id"],
                row["lap_index"],
                row["distance_m"],
                row["elapsed_s"],
                row["pace_per_100m_s"],
                _pace_text(row["pace_per_100m_s"]),
                row["avg_hr"],
                row["max_hr"],
                row["total_strokes"],
                row["swim_stroke_hint"],
                row["swolf_derived"],
                row["is_rest_lap"],
            )
            for row in laps
        ],
    )
    target.commit()
    target.close()
    return _QUERY_DB


def _connect() -> sqlite3.Connection:
    """打开查询库的只读连接。"""
    connection = sqlite3.connect(f"file:{_QUERY_DB}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _strip_sql(query: str) -> str:
    """去掉围栏和末尾分号，只保留一条语句。"""
    text = query.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def _guard_sql(query: str) -> str | None:
    """拒绝写入和多语句。通过时返回 None。"""
    text = _strip_sql(query)
    if ";" in text:
        return "Error: 只允许一条 SELECT。"
    head = text.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        return "Error: 只允许 SELECT。"
    banned = {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "attach",
        "detach",
        "pragma",
        "replace",
        "vacuum",
    }
    tokens = set(re.findall(r"[a-z_]+", head))
    found = tokens & banned
    if found:
        return "Error: 语句包含禁止的关键字：" + "、".join(sorted(found))
    return None


def _execute_select(query: str) -> str:
    """安全门通过后执行一条查询，配速秒数改成分秒再交回。"""
    # 逐行注释：拒绝写入和多语句。没通过就不碰数据库。
    blocked = _guard_sql(query)
    if blocked:
        return blocked
    # 逐行注释：只读连接执行已经摘干净的那一条语句。
    connection = _connect()
    try:
        cursor = connection.execute(_strip_sql(query))
        columns = [item[0] for item in cursor.description or []]
        fetched = cursor.fetchmany(_MAX_ROWS + 1)
    except sqlite3.Error as exc:
        return f"Error: {exc}"
    finally:
        connection.close()
    # 逐行注释：行数过多时让子代理改成聚合，不把整表交回教练。
    if len(fetched) > _MAX_ROWS:
        return f"Error: 结果超过 {_MAX_ROWS} 行。请在 SQL 里聚合或缩小范围。"
    records = [dict(zip(columns, row)) for row in fetched]
    # 逐行注释：数值配速换成已有的分秒，原始秒数不再出现在结果里。
    for record in records:
        for key, value in list(record.items()):
            lowered = key.lower()
            if isinstance(value, (int, float)) and "pace" in lowered and not lowered.endswith("text"):
                record[f"{key}_text"] = _pace_text(value)
    if not records:
        return "查询没有返回行。"
    shown = [
        name
        for name in (list(records[0].keys()))
        if not ("pace" in name.lower() and not name.lower().endswith("text"))
    ]
    header = "\t".join(shown)
    body = "\n".join(
        "\t".join("" if record.get(key) is None else str(record.get(key)) for key in shown)
        for record in records
    )
    return header + "\n" + body


def _extract_sql(text: str) -> str:
    """从模型输出里取出第一条 SELECT 或 WITH。"""
    # 逐行注释：去掉代码围栏和末尾分号，避免安全门把说明文字当成语句。
    stripped = _strip_sql(text)
    match = re.search(r"(?is)\b(with|select)\b[\s\S]+", stripped)
    if match is None:
        return stripped
    return match.group(0).strip()


_SQL_SYSTEM_PROMPT = """
你只负责把查询任务写成一条 SQLite 语句。只输出 SQL，不要解释，不要中文结论。

表已经固定，不要再查表结构。
swim_sessions 一场一行：activity_id, start_time, distance_m, avg_pace_s, avg_pace_text, avg_swolf, avg_hr, max_hr, total_strokes, rest_time_s, rest_ratio。
整场配速用 avg_pace_text，不要用各圈平均代替。
swim_laps 一圈一行：activity_id, lap_index, distance_m, elapsed_s, pace_per_100m_s, pace_text, avg_hr, max_hr, total_strokes, swim_stroke_hint, swolf_derived, is_rest_lap。
单圈配速用 pace_text。elapsed_s 是这一圈用了多少秒。pace_per_100m_s 是秒/100米，不要把它当成这一圈的用时。
swim_stroke_hint 的值包括 自由泳、蛙泳、仰泳。
total_strokes 已是这一圈大约 30 米的划次。要平均就 AVG，不要再除以 100/30 或 3.33。

前后半：先按要求的泳姿过滤，再用 ROW_NUMBER() OVER (ORDER BY lap_index) 和 COUNT(*) OVER ()，n <= total_n / 2 为前半。不要用固定的 lap_index 当中点，也不要把 swim_sessions 的平均值抄进前后半。
多场按 start_time 从早到晚。只选任务要的列。最多 30 行。只写一条 SELECT 或 WITH。
""".strip()


def _write_sql(model: BaseChatModel, task: str, previous_error: str = "") -> str:
    """根据查询任务写一条 SQL。执行失败时把错误交回，再写一次。"""
    # 逐行注释：第一次只给任务。重试时附上安全门或数据库返回的错误。
    user = task if not previous_error else f"{task}\n\n上一条 SQL 未通过：{previous_error}\n请只重写一条 SQL。"
    # 逐行注释：nostream 让这条 SQL 留在工具内部，不流进教练正在说的话。
    response = model.invoke(
        [
            {"role": "system", "content": _SQL_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        config=_QUIET,
    )
    # 逐行注释：有的模型把正文放在 text，有的放在 content。
    raw = getattr(response, "text", None) or getattr(response, "content", "")
    if not isinstance(raw, str):
        raw = str(raw)
    return _extract_sql(raw)


def _honor_time_order(question: str, table: str) -> str:
    """用户要求从早到晚时，按时间列重排查询结果。"""
    # 逐行注释：只在用户明确要求时间顺序时改顺序，避免打乱“最慢几圈”这类结果。
    if "从早到晚" not in question and "按时间" not in question:
        return table
    lines = [line for line in table.splitlines() if line.strip()]
    if len(lines) < 3:
        return table
    columns = lines[0].split("\t")
    time_index = next(
        (index for index, name in enumerate(columns) if "time" in name.lower() or name.lower() == "date"),
        None,
    )
    if time_index is None:
        return table
    rows = [line.split("\t") for line in lines[1:]]
    # 逐行注释：开始时间是文本，按字符串排序与时间先后一致。
    rows.sort(key=lambda row: row[time_index] if time_index < len(row) else "")
    return lines[0] + "\n" + "\n".join("\t".join(row) for row in rows)


def _run_sql_agent(model: BaseChatModel, question: str) -> str:
    """子代理只写 SQL。安全门通过后执行，把带分秒的结果行交回。"""
    logger = logging.getLogger("swim_coach")
    # 逐行注释：第一次只根据查询任务写语句。
    sql = _write_sql(model, question)
    # 逐行注释：安全门和数据库都在程序里。失败只允许再写一次 SQL。
    result = _execute_select(sql)
    if result.startswith("Error"):
        sql = _write_sql(model, question, result)
        result = _execute_select(sql)
    logger.info("sql query=%s result=%s", " ".join(sql.split())[:400], " ".join(result.splitlines()[:3])[:400])
    if result.startswith("Error"):
        return "没有查出可用结果。"
    # 逐行注释：用户要求按时间时，在结果行上重排，不再改写数字。
    return _honor_time_order(question, result)


def build_swim_sql_tool(model: BaseChatModel, repo: SwimRepository):
    """创建 SQL 子代理，并把它包成主教练可调用的一个工具。"""

    @tool
    def ask_swim_database(question: str) -> str:
        """按一条明确的查询任务查游泳数据。场次、配速、SWOLF、泳姿、前后半程、单圈筛选都用这个工具。

        Args:
            question: 查询任务。写清场次范围、泳姿和要的指标，不要传用户原话，也不要写 SQL。
        """
        # 逐行注释：函数一进入就通知设备显示正在查询，不等 SQL 写完。
        from src.agent_runtime import notify_query_started

        notify_query_started()
        # 逐行注释：记下主教练交来的查询任务，和后面的 SQL、结果行对在一起。
        logging.getLogger("swim_coach").info("sql question=%s", " ".join(question.split())[:200])
        # 逐行注释：每次提问前重建只读库，再让子代理只写一条 SQL。
        refresh_query_db(repo)
        # 逐行注释：交回的是带分秒的结果行，教练按这些数字口语转述。
        answer = _run_sql_agent(model, question)
        # 逐行注释：这是查库返回的行，配速已经是分秒。
        logging.getLogger("swim_coach").info("sql answer=%s", " ".join(answer.split())[:400])
        return answer

    return ask_swim_database
