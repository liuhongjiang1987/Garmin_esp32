# 模块级说明：游泳数据的 SQL 子代理（薄实现）。
# 五块：设库 → 安全执行 → 短提示 → 运行 → 暴露 ask_swim_database。
# 主教练只传查询意图；本模块写一条 SELECT、安全执行、返回行。不上四工具循环。

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

# =============================================================================
# 1. 设库：固定两张视图 swim_sessions / swim_laps（结构写死，数据从 evidence 拷）
# =============================================================================
# 不动态 PRAGMA 反射；列名只在本模块短提示里出现，不进主教练 skill。

# 逐行注释：每次提问前刷新的只读查询库路径。
_QUERY_DB = Path(__file__).resolve().parents[1] / "data" / "swim_sql.db"
# 逐行注释：单次最多返回行数。
_MAX_ROWS = 30
# 逐行注释：写 SQL 的模型输出带 nostream，不流进用户听见的话。
_QUIET = {"tags": [TAG_NOSTREAM]}
_LOGGER = logging.getLogger("swim_coach")



def _pace_text(seconds: Any) -> str | None:
    """秒/100米 → 可直接说的分秒。"""
    if seconds is None:
        return None
    total = int(round(float(seconds)))
    return f"{total // 60}分{total % 60:02d}秒/100米"


def refresh_query_db(repo: SwimRepository) -> Path:
    """从 swim_evidence 复制出 swim_sessions / swim_laps 两张固定表。"""
    from src.config import load_settings

    evidence_db = load_settings().swim_evidence_db_path or repo._db_paths.coach_db
    source = sqlite3.connect(f"file:{evidence_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
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


# =============================================================================
# 2. 安全执行：只读门 + 单 SELECT + 行数上限 + 分秒列
# =============================================================================
# 无「最近却 ASC」语义拦截；展示顺序若需要从早到晚，在块 4 结果行重排。


def _connect() -> sqlite3.Connection:
    """打开只读查询库。"""
    connection = sqlite3.connect(f"file:{_QUERY_DB}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _strip_sql(query: str) -> str:
    """去掉代码围栏和末尾分号。"""
    text = query.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def _guard_sql(query: str) -> str | None:
    """安全门：只允许一条 SELECT/WITH。通过返回 None。"""
    text = _strip_sql(query)
    if ";" in text:
        return "Error: 只允许一条 SELECT。"
    head = text.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        return "Error: 只允许 SELECT。"
    banned = {
        "insert", "update", "delete", "drop", "alter", "create",
        "attach", "detach", "pragma", "replace", "vacuum",
    }
    found = set(re.findall(r"[a-z_]+", head)) & banned
    if found:
        return "Error: 语句包含禁止的关键字：" + "、".join(sorted(found))
    return None


def _extract_sql(text: str) -> str:
    """从模型输出里抽出第一条 SELECT/WITH。"""
    stripped = _strip_sql(text)
    match = re.search(r"(?is)\b(with|select)\b[\s\S]+", stripped)
    return match.group(0).strip() if match else stripped


def execute_sql(query: str) -> str:
    """执行一条只读 SQL，返回制表符分隔的结果行（配速已是分秒）。"""
    blocked = _guard_sql(query)
    if blocked:
        return blocked
    connection = _connect()
    try:
        cursor = connection.execute(_strip_sql(query))
        columns = [item[0] for item in cursor.description or []]
        fetched = cursor.fetchmany(_MAX_ROWS + 1)
    except sqlite3.Error as exc:
        return f"Error: {exc}"
    finally:
        connection.close()
    if len(fetched) > _MAX_ROWS:
        return f"Error: 结果超过 {_MAX_ROWS} 行。请缩小范围或做聚合。"
    records = [dict(zip(columns, row)) for row in fetched]
    for record in records:
        for key, value in list(record.items()):
            lowered = key.lower()
            if isinstance(value, (int, float)) and "pace" in lowered and not lowered.endswith("text"):
                record[f"{key}_text"] = _pace_text(value)
    if not records:
        return "查询没有返回行。"
    shown = [
        name
        for name in list(records[0].keys())
        if not ("pace" in name.lower() and not name.lower().endswith("text"))
    ]
    header = "\t".join(shown)
    body = "\n".join(
        "\t".join("" if record.get(key) is None else str(record.get(key)) for key in shown)
        for record in records
    )
    return header + "\n" + body


# =============================================================================
# 3. SQL 角色短提示（schema + 单位 +「最近 = DESC」）
# =============================================================================
# 不做 list_tables / schema / checker 工具循环；提示保持短，无 ASC 长补丁。


_SQL_SYSTEM_PROMPT = """
你是游泳训练库的 SQL 写手。根据查询意图写一条 SQLite 语句。只输出 SQL，不要解释。

固定两张表：
- swim_sessions（一场一行）：activity_id, start_time, distance_m, avg_pace_s, avg_pace_text, avg_swolf, avg_hr, max_hr, total_strokes, rest_time_s, rest_ratio
  整场配速用 avg_pace_text。这张表没有泳姿字段。
- swim_laps（一圈一行）：activity_id, lap_index, distance_m, elapsed_s, pace_per_100m_s, pace_text, avg_hr, max_hr, total_strokes, swim_stroke_hint, swolf_derived, is_rest_lap
  泳姿在 swim_stroke_hint（自由泳/蛙泳/仰泳）。单圈配速用 pace_text。elapsed_s 是圈用时；pace_per_100m_s 是秒/100米。total_strokes 是约 30 米一圈的划次。

「最近」表示时间上最新的场次（ORDER BY start_time DESC）。最多 30 行。只写一条 SELECT 或 WITH。
""".strip()


# =============================================================================
# 4. 运行：写 SQL → 安全执行 →（可选）结果行时间重排
# =============================================================================


def _write_sql(model: BaseChatModel, intent: str, previous_error: str = "") -> str:
    """把查询意图写成一条 SQL；失败时带上错误再写一次。"""
    # 逐行注释：第一次只给意图；重试时附上数据库错误。
    user = intent if not previous_error else f"{intent}\n\n上一条未通过：{previous_error}\n请重写一条 SQL。"
    # 逐行注释：nostream，SQL 原文不流进用户 TTS。
    response = model.invoke(
        [
            {"role": "system", "content": _SQL_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        config=_QUIET,
    )
    raw = getattr(response, "text", None) or getattr(response, "content", "")
    if not isinstance(raw, str):
        raw = str(raw)
    return _extract_sql(raw)


def _order_rows_ascending(table: str) -> str:
    """展示用：若结果含时间列，按从早到晚排。取数仍由 SQL 的 DESC LIMIT 负责「最近」。"""
    # 逐行注释：只重排展示，不改数字，也不改写 SQL。
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
    rows.sort(key=lambda row: row[time_index] if time_index < len(row) else "")
    return lines[0] + "\n" + "\n".join("\t".join(row) for row in rows)


def _run_sql_agent(model: BaseChatModel, intent: str) -> str:
    """运行 SQL 子代理：写 SQL → 安全执行 → 返回结果行。"""
    # 逐行注释：第一步，按意图写 SQL。
    sql = _write_sql(model, intent)
    # 逐行注释：第二步，安全门后执行。
    result = execute_sql(sql)
    # 逐行注释：失败只允许再写一次。
    if result.startswith("Error"):
        sql = _write_sql(model, intent, result)
        result = execute_sql(sql)
    _LOGGER.info(
        "sql query=%s result=%s",
        " ".join(sql.split())[:400],
        " ".join(result.splitlines()[:3])[:400],
    )
    if result.startswith("Error"):
        return "没有查出可用结果。"
    # 逐行注释：意图里若要求从早到晚念，只在结果行上重排。
    if "从早到晚" in intent or "按时间" in intent:
        return _order_rows_ascending(result)
    return result


# =============================================================================
# 5. 暴露工具：build_swim_sql_tool → ask_swim_database
# =============================================================================
# 主教练不写 SQL。它只输出查询意图，并调用本工具；结果行再交回主教练口语转述。


def build_swim_sql_tool(model: BaseChatModel, repo: SwimRepository):
    """把 SQL 子代理包成主教练可调用的一个工具。"""

    @tool
    def ask_swim_database(question: str) -> str:
        """查游泳训练数字。需要距离、配速、SWOLF、划次、场次等任何训练数字时调用。

        Args:
            question: 查询意图，例如「最近三场的距离」或「最近一场的配速和 SWOLF」。不要写 SQL。
        """
        # 逐行注释：一进入就通知设备显示正在查询。
        from src.coach_agent import notify_query_started

        notify_query_started()
        _LOGGER.info("sql question=%s", " ".join(question.split())[:200])
        # 逐行注释：先刷新固定视图，再跑 SQL 子代理。
        refresh_query_db(repo)
        answer = _run_sql_agent(model, question)
        _LOGGER.info("sql answer=%s", " ".join(answer.split())[:400])
        return answer

    return ask_swim_database
