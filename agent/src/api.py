# 模块级说明：内网 HTTP。
# 单次：列表只读 + 同步后预分析；点 ✓ 取报告。
# 趋势：点跨度 POST analyze → 分析中页轮询 GET status → succeeded 再 GET report。

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.advice_queue import (
    ensure_demo_plan,
    get_advice_datapack,
    get_advice_profile,
    get_latest_plan,
    get_plan_status,
    request_plan_analysis,
    run_advice_turn,
)
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
from src.speech import cached_wav, remember_wav, synthesize_wav
from src.trend_analysis_agent import SPAN_DEFS

_LOGGER = logging.getLogger("swim_api")

# 趋势 LLM 串行：并发多跨度易把进程打挂，导致表盘一直停在「分析中」
_trend_job_lock = threading.Lock()


class AfterSyncBody(BaseModel):
    session_limit: int = Field(default=10, ge=1, le=50)
    # 仅消化用户已点选的趋势队列，默认 1；0=不同趋势
    trend_limit: int = Field(default=1, ge=0, le=9)


class AdviceTurnBody(BaseModel):
    """综合建议语音一轮：口语文本 → 槽位更新 + 短回复 + 可选出计划。"""

    text: str = Field(default="", max_length=500)
    athlete_id: str = Field(default="default", max_length=64)
    use_demo: bool = False
    # interview=首次采访；modify=枢纽「修改档案」二级页
    mode: str = Field(default="interview", max_length=32)


class SpeakBody(BaseModel):
    """表盘 TTS：已写好的中文原文 → 16bit/24kHz 单声道 WAV。"""

    text: str = Field(default="", max_length=3000)


class PlanAnalyzeBody(BaseModel):
    """综合建议触发生成计划；demo=true 时直接落设计稿示例课表。"""

    use_demo: bool = False
    athlete_id: str = Field(default="default", max_length=64)


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
    """后台跑该跨度（不阻塞表盘进「分析中」页）；全局串行。"""
    with _trend_job_lock:
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

    @app.post("/speak")
    def speak(body: SpeakBody) -> Response:
        """表盘喇叭：按原文合成 WAV（进综合建议引导 / 回复轮共用）。"""
        spoken = (body.text or "").strip()
        if not spoken:
            raise HTTPException(status_code=400, detail="empty")
        started = time.monotonic()
        try:
            wav = cached_wav(spoken)
            cache_hit = wav is not None
            if wav is None:
                wav = synthesize_wav(
                    spoken,
                    api_key=settings.model_api_key,
                    base_url=settings.model_base_url,
                )
                if len(spoken) <= 80:
                    remember_wav(spoken, wav)
            _LOGGER.info(
                "speak done cache=%s ms=%d bytes=%d chars=%d",
                cache_hit,
                int((time.monotonic() - started) * 1000),
                len(wav),
                len(spoken),
            )
        except Exception as exc:
            _LOGGER.exception("speak failed chars=%d", len(spoken))
            raise HTTPException(status_code=503, detail=str(exc)[:200]) from exc
        return Response(content=wav, media_type="audio/wav")

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
        span = (span or "").strip().lower()
        if span not in SPAN_DEFS:
            raise HTTPException(status_code=400, detail=f"未知跨度，可选 {sorted(SPAN_DEFS)}")
        repo = _repo()
        result = request_trend_analysis(repo, span)
        # 已在 analyzing（含上次 Worker 中断）也重踢，避免卡死在「分析中」
        if result["status"] == STATUS_ANALYZING:
            threading.Thread(
                target=_kick_trend_job,
                args=(span,),
                daemon=True,
                name=f"trend-{span}",
            ).start()
            result = {**result, "started": True}
        return result

    @app.get("/trends/{span}/status")
    def trend_status(span: str) -> dict[str, Any]:
        """分析运行页轮询；can_open=true 时再拉 report。"""
        span = (span or "").strip().lower()
        if span not in SPAN_DEFS:
            raise HTTPException(status_code=400, detail=f"未知跨度，可选 {sorted(SPAN_DEFS)}")
        return get_trend_status(_repo(), span)

    @app.get("/trends/{span}/report")
    def trend_report(span: str) -> dict[str, Any]:
        span = (span or "").strip().lower()
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

    # ── 表盘：综合建议 / 训练计划 ──

    @app.get("/advice/profile")
    def advice_profile() -> dict[str, Any]:
        """首次引导 or 档案摘要；附摘要卡计数。"""
        return get_advice_profile(_repo())

    @app.post("/advice/turn")
    def advice_turn(body: AdviceTurnBody) -> dict[str, Any]:
        """表盘聆听确认后：抽槽位、短回复、槽位齐或明确意图时触发出计划。"""
        return run_advice_turn(
            _repo(),
            body.text,
            athlete_id=body.athlete_id,
            settings=settings,
            use_demo=body.use_demo,
            mode=body.mode,
        )

    @app.get("/advice/datapack")
    def advice_datapack(user_request: str | None = None) -> dict[str, Any]:
        """§3.2 Data pack：档案 + 预装单次/趋势摘要卡（出计划 / 语音轮用）。"""
        return get_advice_datapack(_repo(), user_request=user_request)

    @app.get("/advice/plan/status")
    def advice_plan_status() -> dict[str, Any]:
        """CTA：idle|analyzing|succeeded|failed + can_open。"""
        return get_plan_status(_repo())

    @app.get("/advice/plan")
    def advice_plan(demo_if_empty: bool = True) -> dict[str, Any]:
        """最新计划（含 pages 翻页单元）。默认无计划时种入设计稿示例便于联调。"""
        repo = _repo()
        plan = get_latest_plan(repo)
        if plan is None and demo_if_empty:
            plan = ensure_demo_plan(repo)
        if plan is None:
            raise HTTPException(status_code=404, detail="尚无训练计划")
        return plan

    @app.post("/advice/plan/analyze")
    def advice_plan_analyze(use_demo: bool = False, athlete_id: str = "default") -> dict[str, Any]:
        """触发生成；后台跑，CTA 转圈。默认走 arena-plan Skill；联调 demo 传 ?use_demo=true。"""
        return request_plan_analysis(
            _repo(),
            settings,
            athlete_id=athlete_id,
            use_demo=use_demo,
        )

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
