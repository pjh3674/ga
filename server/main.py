"""GA Debate Arena — FastAPI server.

Wraps the existing Python toolkit (debate.py, db.py, config.py, integrations)
and exposes REST + SSE endpoints for the Next.js frontend.

Run (dev):
    cd /home/pjh/apps/ga
    uvicorn server.main:app --host 0.0.0.0 --port 8600 --reload
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

# Make the ga package importable when launched from anywhere.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .schemas import (
    ArchiveGroup,
    ArchiveItem,
    ConfigBundle,
    DailySummaryRequest,
    DailySummaryResponse,
    DebateResumeRequest,
    DebateStartRequest,
    DebateStartResponse,
    ModelCacheStatus,
    ModelOption,
    OpsMetricsResponse,
    ProfilePreset,
    RagArchiveListResponse,
    RagArchiveToggleRequest,
    RagArchiveToggleResponse,
    RagCollectionStat,
    RefineryRunSummary,
    RefinerySaveRequest,
    RefinerySaveResponse,
    RefineryStartRequest,
    RefineryStartResponse,
    ServiceStatus,
    SystemStatusResponse,
)
from .streaming import (
    event_stream,
    get_session,
    start_debate_stream,
    start_refinery_stream,
)

app = FastAPI(title="GA Debate Arena API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # served on Tailscale-only network
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    from db import init_db

    init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ───────────────────────── Config ─────────────────────────
@app.get("/api/config", response_model=ConfigBundle)
def get_config(profile: str = "balanced") -> ConfigBundle:
    """Return UI config. `profile` controls which `recommended` map is returned
    so the frontend can refresh per-role suggestions when the user switches
    the cost profile."""
    import config as cfg

    profile_presets = cfg.get_profile_presets() or {}
    profiles = [
        ProfilePreset(id=k, label=v.get("label", k))
        for k, v in profile_presets.items()
    ]

    modes = cfg.load_debate_modes() or {}
    mode_list = [
        {"id": m.get("id", k), "label": m.get("label", k), "icon": m.get("icon", "")}
        for k, m in modes.items()
    ]

    static_backends = cfg.AGENT_BACKEND_OPTIONS or {}
    free_backends = cfg.get_free_models_as_backends() or {}
    or_backends = cfg.get_cached_openrouter_models_as_backends() or {}

    backends: list[ModelOption] = []
    seen: set[str] = set()
    # Static (curated) first — they sort to the top of selectors.
    for k in static_backends:
        if k in seen:
            continue
        backends.append(ModelOption(key=k, label=k, provider="static"))
        seen.add(k)
    for k in free_backends:
        if k in seen:
            continue
        backends.append(ModelOption(key=k, label=k, provider="free"))
        seen.add(k)
    for k in or_backends:
        if k in seen:
            continue
        backends.append(ModelOption(key=k, label=k, provider="openrouter"))
        seen.add(k)

    recommended = cfg.get_auto_recommended_backends(profile) or {}
    if not recommended:
        recommended = cfg.get_default_free_backends() or {}

    try:
        from debate import PERSONA_LABELS

        personas = dict(PERSONA_LABELS)
    except Exception:
        personas = {}

    return ConfigBundle(
        profiles=profiles or [ProfilePreset(id="balanced", label="균형")],
        modes=mode_list or [{"id": "debate", "label": "찬반토론", "icon": "⚖️"}],
        backends=backends,
        recommended=recommended,
        personas=personas,
    )


@app.get("/api/defaults")
def get_defaults() -> dict[str, str]:
    """Free-tier safe defaults — used by the '기본' button on the frontend."""
    import config as cfg

    return cfg.get_default_free_backends() or {}


# ───────────────────────── Archive ─────────────────────────
def _group_label(created_iso: str, today: _dt.date, yesterday: _dt.date) -> str:
    try:
        d = _dt.datetime.fromisoformat(created_iso[:19]).date()
    except Exception:
        return "이전"
    if d == today:
        return "오늘"
    if d == yesterday:
        return "어제"
    return "이전"


@app.get("/api/debates", response_model=list[ArchiveGroup])
def list_debates() -> list[ArchiveGroup]:
    from db import fetch_all_debates

    rows = fetch_all_debates() or []
    today = _dt.date.today()
    yesterday = today - _dt.timedelta(days=1)

    grouped: dict[str, list[ArchiveItem]] = {"오늘": [], "어제": [], "이전": []}
    for r in rows:
        d = dict(r)
        label = _group_label(str(d.get("created", "")), today, yesterday)
        grouped[label].append(
            ArchiveItem(
                id=int(d["id"]),
                topic=str(d.get("topic", "")),
                created=str(d.get("created", "")),
                summary=str(d.get("summary", "") or ""),
                verdict=str(d.get("verdict", "") or ""),
                debate_mode=str(d.get("debate_mode", "debate") or "debate"),
                thread_id=(int(d["thread_id"]) if d.get("thread_id") is not None else None),
            )
        )
    return [ArchiveGroup(label=k, items=v) for k, v in grouped.items()]


# ───────────────────────── System Status ─────────────────────────
_STATUS_CACHE_TTL = 60  # 초

@app.get("/api/system-status", response_model=SystemStatusResponse)
async def system_status() -> SystemStatusResponse:
    """항만연안재생과 AI 관제실 — 실시간 시스템 현황 집계.

    Redis에 60초 캐싱하여 30초 폴링 클라이언트가 다수여도 백엔드 부하를 억제한다.
    Redis 장애 시에는 캐시 우회하여 항상 실시간 집계.
    """
    import datetime as dt
    import json as _json

    # ── 캐시 조회 (Redis 사용 가능 시) ────────────────────────────────
    _cache_key = "ga:system_status:v1"
    try:
        import redis as _redis
        _rc = _redis.Redis(host="redis", port=6379, socket_timeout=1)
        _cached = _rc.get(_cache_key)
        if _cached:
            return SystemStatusResponse(**_json.loads(_cached))
    except Exception:
        _rc = None  # 캐시 우회
    import requests as _req
    from pathlib import Path

    now = dt.datetime.now().isoformat(timespec="seconds")

    # ── RAG 컬렉션 통계 ──────────────────────────────────────────────
    rag_stats: list[RagCollectionStat] = []
    try:
        r = _req.get("http://172.17.0.1:8400/status", timeout=5)
        if r.ok:
            for name, info in r.json().items():
                rag_stats.append(RagCollectionStat(
                    name=name,
                    label=info.get("label", name),
                    total_documents=info.get("total_documents", 0),
                    total_chunks=info.get("total_chunks", 0),
                    index_running=info.get("index_running", False),
                ))
    except Exception as e:
        pass

    # ── 서비스 상태 ──────────────────────────────────────────────────
    services: list[ServiceStatus] = []

    # hwp-rag
    try:
        r2 = _req.get("http://172.17.0.1:8400/collections", timeout=3)
        services.append(ServiceStatus(
            name="hwp-rag",
            status="healthy" if r2.ok else "degraded",
            detail=f"컬렉션 {len(r2.json())}개" if r2.ok else r2.text[:60],
        ))
    except Exception as e:
        services.append(ServiceStatus(name="hwp-rag", status="down", detail=str(e)[:80]))

    # ga-api self
    services.append(ServiceStatus(name="ga-api", status="healthy", detail="self"))

    # redis
    try:
        import redis as _redis
        rc = _redis.Redis(host="redis", port=6379, socket_timeout=2)
        rc.ping()
        info = rc.info("server")
        services.append(ServiceStatus(
            name="redis",
            status="healthy",
            detail=f"v{info.get('redis_version','?')} | {info.get('connected_clients',0)}클라이언트",
        ))
    except Exception as e:
        services.append(ServiceStatus(name="redis", status="down", detail=str(e)[:80]))

    # ── NAS 마운트 확인 ──────────────────────────────────────────────
    nas_path = Path("/mnt/nas")
    nas_ok = False
    nas_detail = ""
    try:
        test_file = nas_path / ".ga_healthcheck"
        test_file.write_text("ok")
        test_file.unlink()
        nas_ok = True
        # NAS 여유 공간
        import shutil as _sh
        usage = _sh.disk_usage(str(nas_path))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        nas_detail = f"여유 {free_gb:.1f}GB / 전체 {total_gb:.0f}GB"
    except Exception as e:
        nas_detail = str(e)[:80]

    # ── 토론 통계 ────────────────────────────────────────────────────
    debate_stats: dict = {}
    try:
        from db import fetch_debate_stats
        debate_stats = dict(fetch_debate_stats() or {})
    except Exception:
        pass

    response = SystemStatusResponse(
        timestamp=now,
        rag_collections=rag_stats,
        services=services,
        debate_stats=debate_stats,
        nas_ok=nas_ok,
        nas_detail=nas_detail,
    )

    # ── 캐시 저장 (Redis 사용 가능 시) ────────────────────────────────
    if _rc is not None:
        try:
            _rc.setex(_cache_key, _STATUS_CACHE_TTL, response.model_dump_json())
        except Exception:
            pass

    return response


@app.get("/api/ops-metrics", response_model=OpsMetricsResponse)
def ops_metrics(days: int = 7) -> OpsMetricsResponse:
    """운영 관제용 통합 메트릭 — N일 추세, 정제소·스레드·비용 통계."""
    from db import fetch_ops_metrics

    days = max(1, min(days, 90))
    m = fetch_ops_metrics(days=days)
    return OpsMetricsResponse(**m)


@app.post("/api/ops/daily-summary", response_model=DailySummaryResponse)
def post_daily_summary(req: DailySummaryRequest) -> DailySummaryResponse:
    """Phase 4: 지정 일자(기본 어제)의 GA 활동을 Obsidian Daily Note에 prepend + 보관 노트 저장."""
    from integrations.daily_summary import generate_daily_summary

    res = generate_daily_summary(req.date)
    return DailySummaryResponse(**res)


# ── Phase 5: 모델 캐시 관제 ─────────────────────────────────────────────────────
def _read_model_cache_status() -> ModelCacheStatus:
    import json, datetime
    from pathlib import Path

    cache_file = Path(__file__).resolve().parents[1] / "model_cache.json"
    if not cache_file.exists():
        return ModelCacheStatus()
    try:
        data = json.loads(cache_file.read_text())
    except Exception:
        return ModelCacheStatus()

    meta = data.get("recommendation_metadata") or {}
    updated_at = str(data.get("updated_at", ""))
    age = None
    if updated_at:
        try:
            dt = datetime.datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
            age = max(0, int((datetime.datetime.now() - dt).total_seconds() / 60))
        except Exception:
            pass
    return ModelCacheStatus(
        updated_at=updated_at,
        schema_version=int(data.get("schema_version", 0)),
        free_count=int(meta.get("free_count", 0)),
        paid_count=int(meta.get("paid_count", 0)),
        cleaned_total=int(meta.get("cleaned_total", 0)),
        weight_changes=list(meta.get("weight_changes") or []),
        default_per_role=dict(data.get("default_free_per_role") or {}),
        auto_recommended=str(data.get("auto_recommended", "")),
        profiles=list((data.get("default_per_role_by_profile") or {}).keys()),
        age_minutes=age,
    )


@app.get("/api/ops/model-cache-status", response_model=ModelCacheStatus)
def get_model_cache_status() -> ModelCacheStatus:
    """Phase 5: model_cache.json 메타데이터 조회 (갱신 주기/가중치 튜닝 내역 포함)."""
    return _read_model_cache_status()


@app.post("/api/ops/refresh-models")
def post_refresh_models():
    """Phase 5: update_model.main()을 동기 실행해 최신 OpenRouter 리스트 + 가중치 튜닝 적용.

    주의: API 호출에 몇 – 30초 걸림. 웹 요청에서는 timeout 고려 필요.
    """
    import io, time, contextlib
    from fastapi.responses import JSONResponse

    buf = io.StringIO()
    err = ""
    ok = True
    t0 = time.time()
    try:
        from update_model import main as update_main
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            update_main()
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {e}"
    elapsed = round(time.time() - t0, 2)

    log_tail = "\n".join(buf.getvalue().splitlines()[-15:])
    payload = {
        "ok": ok,
        "elapsed_sec": elapsed,
        "log_tail": log_tail,
        "error": err,
        "status": _read_model_cache_status().model_dump(),
    }
    return JSONResponse(payload, status_code=200 if ok else 500)


# ── Phase 1-1 GA 연계: RAG 아카이브 관리 ──────────────────────────
@app.get("/api/rag/archived", response_model=RagArchiveListResponse)
def get_rag_archived(collection: str = "wisdom_base") -> RagArchiveListResponse:
    """hwp-rag에서 아카이브된 문서 목록 조회."""
    from search.rag_search import list_archived_docs

    items = list_archived_docs(collection)
    return RagArchiveListResponse(collection=collection, items=items)


@app.post("/api/rag/archive", response_model=RagArchiveToggleResponse)
def post_rag_archive(req: RagArchiveToggleRequest) -> RagArchiveToggleResponse:
    """hwp-rag 문서의 archived 플래그를 토글. archived=False로 보내면 복원."""
    from search.rag_search import set_archived

    ok, err = set_archived(req.collection, req.filepath, req.archived)
    return RagArchiveToggleResponse(ok=ok, error=err)


@app.get("/api/debates/{debate_id}")
def get_debate(debate_id: int) -> dict:
    from db import fetch_debate_by_id

    res = fetch_debate_by_id(debate_id)
    if not res:
        raise HTTPException(404, "debate not found")
    return res


@app.get("/api/debates/{debate_id}/thread")
def get_debate_thread(debate_id: int) -> list[dict]:
    """해당 토론이 속한 스레드의 모든 토론(자기 자신 포함)을 시간순 반환."""
    from db import fetch_debate_by_id, fetch_thread_debates

    cur = fetch_debate_by_id(debate_id)
    if not cur:
        raise HTTPException(404, "debate not found")
    tid = cur.get("thread_id") or debate_id
    rows = fetch_thread_debates(tid) or []
    if not rows:
        # 단일 토론(아직 resume 안 됨) — 자기 자신만 반환
        return [{
            "id": cur["id"],
            "topic": cur.get("topic", ""),
            "created": cur.get("created", ""),
            "summary": cur.get("summary", ""),
            "verdict": cur.get("verdict", ""),
            "thread_id": tid,
        }]
    return rows


# ───────────────────────── Run + Stream ─────────────────────────
@app.post("/api/debates/run", response_model=DebateStartResponse)
async def start_run(req: DebateStartRequest) -> DebateStartResponse:
    session = start_debate_stream(req.model_dump())
    return DebateStartResponse(debate_id=session.id)


@app.post("/api/debates/{debate_id}/resume", response_model=DebateStartResponse)
async def resume_run(debate_id: int, req: DebateResumeRequest) -> DebateStartResponse:
    """이전 토론의 verdict와 마지막 발언을 컨텍스트로 prefill하여 추가 라운드 진행.

    같은 thread_id로 묶여 이력에서 연속 토론으로 표시된다.
    """
    from db import fetch_debate_by_id

    prev = fetch_debate_by_id(debate_id)
    if not prev:
        raise HTTPException(404, "previous debate not found")

    prev_msgs = prev.get("messages") or []
    verdict = (prev.get("verdict") or "").strip()
    debate_mode = prev.get("debate_mode") or "debate"
    thread_id = prev.get("thread_id") or debate_id  # 첫 resume이면 prev id로 묶음

    # 마지막 6개 발언 발췌 (각 600자 컷)
    tail = prev_msgs[-6:]
    def _fmt(m: dict) -> str:
        c = (m.get("content") or "").strip().replace("\n\n", "\n")
        if len(c) > 600:
            c = c[:600] + "…"
        return f"[{m.get('role','?')}/{m.get('name','?')}] {c}"
    history_text = "\n\n".join(_fmt(m) for m in tail) or "(이전 발언 없음)"

    new_context = (
        f"### 이전 토론 결과 요약\n"
        f"- 이전 주제: {prev.get('topic')}\n"
        f"- 이전 모드: {debate_mode}\n\n"
        f"### 직전 판정관 결론\n{verdict or '(판정 미기록)'}\n\n"
        f"### 마지막 발언 발췌 (최대 6개)\n{history_text}\n\n"
        f"### 사용자 추가 조건 / 새 변수\n{req.extra_input}\n\n"
        f"위 추가 조건을 반영하여 토론을 이어가라. "
        f"이미 합의된 항목을 다시 다투지 말고, 새 변수의 영향을 중심으로 논의하라."
    )

    payload = {
        "topic": prev.get("topic", "(unknown)"),
        "context": new_context,
        "persona": req.persona or "balanced",
        "use_web_search": req.use_web_search,
        "use_rag": req.use_rag,
        "rag_collection": req.rag_collection,
        "agent_backends": req.agent_backends or {},
        "quality_profile": req.quality_profile,
        "auto_model_enabled": req.auto_model_enabled,
        "debate_mode": debate_mode,
        "max_rounds": req.max_rounds,
        "save_obsidian": req.save_obsidian,
        "thread_id": thread_id,
    }
    session = start_debate_stream(payload)
    return DebateStartResponse(debate_id=session.id)


@app.get("/api/debates/run/{sid}/stream")
async def stream_run(sid: str):
    session = get_session(sid)
    if not session:
        raise HTTPException(404, "stream not found or already consumed")

    async def gen():
        async for chunk in event_stream(session):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
            "Connection": "keep-alive",
        },
    )


# ───────────────────────── Refinery (Phase 2) ─────────────────────────
@app.post("/api/refinery/run", response_model=RefineryStartResponse)
async def start_refinery(req: RefineryStartRequest) -> RefineryStartResponse:
    session = start_refinery_stream(req.model_dump())
    return RefineryStartResponse(sid=session.id)


@app.get("/api/refinery/run/{sid}/stream")
async def stream_refinery(sid: str):
    session = get_session(sid)
    if not session:
        raise HTTPException(404, "stream not found or already consumed")

    async def gen():
        async for chunk in event_stream(session):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/refinery/save", response_model=RefinerySaveResponse)
def save_refinery(req: RefinerySaveRequest) -> RefinerySaveResponse:
    """편집된 정제 결과를 Obsidian 볼트에 저장."""
    try:
        from integrations.obsidian_save import save_refinery_output
        from db import log_save_result

        res = save_refinery_output(
            topic=req.topic,
            report_md=req.edited_md,
            critique_md=req.critique_md,
            citations=req.citations,
            run_id=req.run_id,
        )
        ok = bool(getattr(res, "ok", False))
        path = getattr(res, "vault_path", None)
        try:
            log_save_result(res, ref_id=req.run_id, ref_type="refinery")
        except Exception:
            pass
        return RefinerySaveResponse(
            ok=ok, obsidian_path=path, run_id=req.run_id,
            detail="" if ok else "save_to_obsidian returned ok=False",
        )
    except Exception as e:  # noqa: BLE001
        return RefinerySaveResponse(
            ok=False, obsidian_path=None, run_id=req.run_id, detail=f"{type(e).__name__}: {e}"
        )


@app.get("/api/refinery/runs", response_model=list[RefineryRunSummary])
def list_refinery_runs(limit: int = 50) -> list[RefineryRunSummary]:
    """최근 정제 실행 이력."""
    from db import fetch_refinery_runs
    rows = fetch_refinery_runs(limit=limit) or []
    return [
        RefineryRunSummary(
            id=int(r.get("id", 0)),
            topic=str(r.get("topic", "")),
            created=str(r.get("created", "")),
            source_ai=str(r.get("source_ai", "") or ""),
            template_id=str(r.get("template_id", "") or ""),
            status=str(r.get("status", "") or ""),
        )
        for r in rows
    ]
