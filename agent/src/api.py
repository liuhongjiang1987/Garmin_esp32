# 模块级说明：内网 HTTP。
# 单次：列表只读 + 同步后预分析；点 ✓ 取报告。
# 趋势：点跨度 POST analyze → 分析中页轮询 GET status → succeeded 再 GET report。

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.analysis_queue import (
    STATUS_ANALYZING,
    STATUS_SUCCEEDED,
    after_sync,
    get_session_report,
    get_trend_report,
    get_trend_status,
    list_sessions_for_ui,
    list_trends_for_ui,
    process_session_jobs,
    process_trend_jobs,
    request_trend_analysis,
)
from src.config import load_settings
from src.db.schema import init_coach_db
from src.repository.swim_repo import DbPaths, SwimRepository
from src.trend_analysis_agent import SPAN_DEFS

_LOGGER = logging.getLogger("swim_api")


class AfterSyncBody(BaseModel):
    session_limit: int = Field(default=10, ge=1, le=50)
    # 仅消化用户已点选的趋势队列，默认 1；0=不同趋势
    trend_limit: int = Field(default=1, ge=0, le=9)


def _repo() -> SwimRepository:
    settings = load_settings()
    init_coach_db(settings.coach_db_path)
    return SwimRepository(
        DbPaths(
            coach_db=settings.coach_db_path,
            garmin_db=settings.garmin_db_path,
            garmin_activities_db=settings.garmin_activities_db_path,
        )
    )


def _kick_trend_job(span: str) -> None:
    """后台跑该跨度（不阻塞表盘进「分析中」页）。"""
    try:
        settings = load_settings()
        repo = _repo()
        process_trend_jobs(repo, settings, limit=1, only_span=span)
    except Exception:
        _LOGGER.exception("background trend job failed span=%s", span)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    app = FastAPI(title="Ian swim analysis API", version="2.0.0")
    settings = load_settings()

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    # ── 表盘：单次只读 ──

    @app.get("/sessions")
    def sessions(limit: int = 20) -> dict[str, Any]:
        """单次分析列表：含 status / can_open（对应转圈与 ✓）。"""
        repo = _repo()
        return {"items": list_sessions_for_ui(repo, limit=limit)}

    @app.get("/sessions/{activity_id}/report")
    def session_report(activity_id: str) -> dict[str, Any]:
        """仅 succeeded 可取；分析中返回 409。"""
        repo = _repo()
        report = get_session_report(repo, activity_id)
        if report is None:
            items = {i["activity_id"]: i for i in list_sessions_for_ui(repo, limit=200)}
            item = items.get(activity_id)
            if item and item["status"] != STATUS_SUCCEEDED:
                raise HTTPException(status_code=409, detail=f"分析未完成: {item['status']}")
            raise HTTPException(status_code=404, detail="报告不存在")
        return report

    # ── 表盘：趋势点选触发 ──

    @app.get("/trends")
    def trends() -> dict[str, Any]:
        """九宫格状态：idle|analyzing|succeeded|failed；不预跑。"""
        repo = _repo()
        return {"items": list_trends_for_ui(repo)}

    @app.post("/trends/{span}/analyze")
    def trend_analyze(span: str) -> dict[str, Any]:
        """点某跨度：cached=true 则直开详情；否则入队并后台跑，前端进分析中页。"""
        if span not in SPAN_DEFS:
            raise HTTPException(status_code=400, detail=f"未知跨度，可选 {sorted(SPAN_DEFS)}")
        repo = _repo()
        result = request_trend_analysis(repo, span)
        if result["status"] == STATUS_ANALYZING and result.get("started"):
            threading.Thread(
                target=_kick_trend_job,
                args=(span,),
                daemon=True,
                name=f"trend-{span}",
            ).start()
        return result

    @app.get("/trends/{span}/status")
    def trend_status(span: str) -> dict[str, Any]:
        """分析运行页轮询；can_open=true 时再拉 report。"""
        if span not in SPAN_DEFS:
            raise HTTPException(status_code=400, detail=f"未知跨度，可选 {sorted(SPAN_DEFS)}")
        return get_trend_status(_repo(), span)

    @app.get("/trends/{span}/report")
    def trend_report(span: str) -> dict[str, Any]:
        if span not in SPAN_DEFS:
            raise HTTPException(status_code=400, detail=f"未知跨度，可选 {sorted(SPAN_DEFS)}")
        repo = _repo()
        report = get_trend_report(repo, span)
        if report is None:
            st = get_trend_status(repo, span)
            if st["status"] == STATUS_ANALYZING:
                raise HTTPException(status_code=409, detail="分析中", headers={"X-Trend-Status": STATUS_ANALYZING})
            raise HTTPException(status_code=409, detail=f"趋势报告未就绪: {st['status']}")
        return report

    # ── 同步后 / Worker ──

    @app.post("/internal/after-sync")
    def internal_after_sync(body: AfterSyncBody) -> dict[str, Any]:
        """Garmin 同步后：单次入队处理；趋势缓存作废；不预跑九档。"""
        repo = _repo()
        try:
            return after_sync(
                repo,
                settings,
                session_limit=body.session_limit,
                trend_limit=body.trend_limit,
            )
        except Exception as exc:
            _LOGGER.exception("after-sync failed")
            raise HTTPException(status_code=500, detail=type(exc).__name__) from exc

    @app.post("/internal/process-jobs")
    def internal_process_jobs() -> dict[str, Any]:
        """定时扫队列（消化单次 + 用户已点选的趋势）。"""
        repo = _repo()
        return {
            "session": process_session_jobs(repo, settings),
            "trend": process_trend_jobs(repo, settings),
        }

    return app
