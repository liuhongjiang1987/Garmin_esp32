# 模块级说明：读取 Garmin 导出的泳池 CSV，按行类型分层并输出可计算结构。

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def parse_swim_csv(csv_path: Path) -> list[dict[str, Any]]:
    """读取泳池 CSV 行数据。"""
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            rows.append(row)
    return rows


def extract_summary_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """提取 '摘要信息' 行。"""
    for row in rows:
        if row.get("间歇训练") == "摘要信息":
            return row
    return None


def parse_cn_number(value: str | None) -> float | None:
    """解析中文 CSV 数值（处理千分位逗号与空值）。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_time_to_seconds(value: str | None) -> float | None:
    """解析 m:ss(.x) 或 h:mm:ss(.x) 文本到秒。"""
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "--", "0"}:
        return 0.0 if text == "0" else None
    parts = text.split(":")
    try:
        if len(parts) == 2:
            minute = int(parts[0])
            second = float(parts[1])
            return minute * 60 + second
        if len(parts) == 3:
            hour = int(parts[0])
            minute = int(parts[1])
            second = float(parts[2])
            return hour * 3600 + minute * 60 + second
    except ValueError:
        return None
    return None


def parse_summary_metrics(summary_row: dict[str, Any] | None) -> dict[str, Any] | None:
    """将摘要行转换为统一指标结构。"""
    if not summary_row:
        return None
    return {
        "total_distance_m": parse_cn_number(summary_row.get("距离")),
        "total_time_s": parse_time_to_seconds(summary_row.get("时间")),
        "avg_pace_per_100m_s": parse_time_to_seconds(summary_row.get("平均配速")),
        "best_pace_per_100m_s": parse_time_to_seconds(summary_row.get("最佳配速")),
        "avg_swolf": parse_cn_number(summary_row.get("平均 Swolf")),
        "avg_hr": parse_cn_number(summary_row.get("平均心率")),
        "max_hr": parse_cn_number(summary_row.get("最大心率")),
        "total_strokes": parse_cn_number(summary_row.get("总划水次数")),
        "avg_strokes_per_length": parse_cn_number(summary_row.get("平均划数")),
        "calories": parse_cn_number(summary_row.get("热量消耗")),
    }


@dataclass
class ParsedCsvActivity:
    """CSV 活动结构化结果。"""

    activity_id: str
    summary_metrics: dict[str, Any] | None
    child_rows: list[dict[str, Any]]
    parent_rows: list[dict[str, Any]]
    rest_rows: list[dict[str, Any]]
    all_rows: list[dict[str, Any]]


def classify_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """将 CSV 行分类为子圈、父圈、休息。"""
    child_rows: list[dict[str, Any]] = []
    parent_rows: list[dict[str, Any]] = []
    rest_rows: list[dict[str, Any]] = []
    for row in rows:
        interval = (row.get("间歇训练") or "").strip()
        stroke = (row.get("泳姿") or "").strip()
        distance = parse_cn_number(row.get("距离")) or 0.0

        if interval == "摘要信息":
            continue
        if stroke == "休息" or distance == 0:
            rest_rows.append(row)
            continue
        if interval and "." in interval:
            child_rows.append(row)
        elif interval:
            parent_rows.append(row)
    return child_rows, parent_rows, rest_rows


def parse_activity_from_csv(csv_path: Path) -> ParsedCsvActivity:
    """解析一场 CSV 活动。"""
    rows = parse_swim_csv(csv_path)
    summary = parse_summary_metrics(extract_summary_row(rows))
    child_rows, parent_rows, rest_rows = classify_rows(rows)
    activity_id = csv_path.stem.replace("activity_", "")
    return ParsedCsvActivity(
        activity_id=activity_id,
        summary_metrics=summary,
        child_rows=child_rows,
        parent_rows=parent_rows,
        rest_rows=rest_rows,
        all_rows=rows,
    )

