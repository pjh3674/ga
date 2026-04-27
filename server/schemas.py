from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class AgentBackends(BaseModel):
    pro: str | None = None
    con: str | None = None
    judge: str | None = None
    fact: str | None = None
    audience: str | None = None


class DebateStartRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    context: str = ""
    persona: str = "balanced"
    debate_mode: str = "debate"
    quality_profile: Literal["economy", "balanced", "quality"] = "balanced"
    max_rounds: int = 3
    use_web_search: bool = False
    use_rag: bool = False
    rag_collection: str = "budget"
    use_polymarket: bool = False
    auto_model_enabled: bool = True
    agent_backends: AgentBackends | None = None
    save_obsidian: bool = True


class DebateStartResponse(BaseModel):
    debate_id: str  # transient stream id, not yet persisted


class MessageEvent(BaseModel):
    type: Literal["message"] = "message"
    role: str
    speaker: str
    content: str
    round: int | None = None
    model: str | None = None


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    stage: str  # "starting" | "round" | "saving" | "done" | "error"
    round: int | None = None
    message: str | None = None


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    debate_id: int  # persisted DB id
    verdict: str
    saved_obsidian: bool
    saved_path: str | None


class ArchiveItem(BaseModel):
    id: int
    topic: str
    created: str
    summary: str
    verdict: str
    debate_mode: str
    thread_id: int | None = None


class ArchiveGroup(BaseModel):
    label: str  # "오늘", "어제", "이전"
    items: list[ArchiveItem]


class ModelOption(BaseModel):
    key: str
    label: str
    provider: str  # "free" | "openrouter" | "static"


class ProfilePreset(BaseModel):
    id: str
    label: str


class ConfigBundle(BaseModel):
    profiles: list[ProfilePreset]
    modes: list[dict[str, Any]]
    backends: list[ModelOption]
    recommended: dict[str, str]  # role -> backend_key
    personas: dict[str, str]


class RagCollectionStat(BaseModel):
    name: str
    label: str
    total_documents: int
    total_chunks: int
    index_running: bool


class ServiceStatus(BaseModel):
    name: str
    status: str   # "healthy" | "degraded" | "down"
    detail: str = ""


class SystemStatusResponse(BaseModel):
    timestamp: str
    rag_collections: list[RagCollectionStat]
    services: list[ServiceStatus]
    debate_stats: dict[str, Any]
    nas_ok: bool
    nas_detail: str = ""


# ── 운영 관제 메트릭 (Phase 3) ───────────────────────────────────────
class DailyPoint(BaseModel):
    day: str
    cnt: int = 0
    cost: float = 0.0
    p_tok: int = 0
    c_tok: int = 0


class TopCostModel(BaseModel):
    model: str
    cost: float = 0.0
    calls: int = 0


class StatusCount(BaseModel):
    status: str
    cnt: int


class OpsMetricsResponse(BaseModel):
    window_days: int
    debates_daily: list[DailyPoint]
    refinery_daily: list[DailyPoint]
    cost_daily: list[DailyPoint]
    refinery_by_status: list[StatusCount]
    refinery_total: int
    thread_total: int
    threads_with_resume: int
    max_rounds_in_thread: int
    top_cost_models: list[TopCostModel]


# ── 일일 요약 (Phase 4) ────────────────────────────────────────────────────
class DailySummaryRequest(BaseModel):
    date: str | None = None  # YYYY-MM-DD, 생략 시 어제


class DailySummaryTarget(BaseModel):
    ok: bool
    path: str = ""
    error: str = ""


class DailySummaryResponse(BaseModel):
    date: str
    summary_markdown: str
    daily_note: DailySummaryTarget
    archive: DailySummaryTarget


# ── 모델 캐시 상태 (Phase 5) ───────────────────────────────
class ModelCacheStatus(BaseModel):
    updated_at: str = ""
    schema_version: int = 0
    free_count: int = 0
    paid_count: int = 0
    cleaned_total: int = 0
    weight_changes: list[str] = []
    default_per_role: dict[str, str] = {}
    auto_recommended: str = ""
    profiles: list[str] = []
    age_minutes: int | None = None


class RefreshModelsResponse(BaseModel):
    ok: bool
    elapsed_sec: float
    log_tail: str = ""
    error: str = ""
    status: ModelCacheStatus | None = None


# ── RAG 아카이브 (Phase 1-1 GA 연계) ──────────────────────────
class RagArchivedDoc(BaseModel):
    filepath: str
    title: str = ""
    chunk_count: int = 0


class RagArchiveListResponse(BaseModel):
    collection: str
    items: list[RagArchivedDoc]


class RagArchiveToggleRequest(BaseModel):
    collection: str
    filepath: str = Field(..., min_length=1)
    archived: bool = True


class RagArchiveToggleResponse(BaseModel):
    ok: bool
    error: str = ""


# ── 정제소 (Phase 2) ───────────────────────────────────────────────────────
class RefineryStartRequest(BaseModel):
    raw_text: str = Field(..., min_length=10)
    topic: str = Field(..., min_length=1)
    source_ai: str = ""
    template_id: str = "jangan_base"
    use_wisdom_rag: bool = True
    use_alignment: bool = True
    use_critique: bool = True
    quality: Literal["economy", "balanced", "quality"] = "balanced"
    backend_key: str = ""


class RefineryStartResponse(BaseModel):
    sid: str  # transient stream id


class RefinerySaveRequest(BaseModel):
    edited_md: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    critique_md: str = ""
    citations: list[str] = Field(default_factory=list)
    run_id: int = 0


class RefinerySaveResponse(BaseModel):
    ok: bool
    obsidian_path: str | None = None
    run_id: int = 0
    detail: str = ""


class RefineryRunSummary(BaseModel):
    id: int
    topic: str
    created: str
    source_ai: str
    template_id: str
    status: str


# ── 토론 Resume (Phase 2-2) ────────────────────────────────────────────
class DebateResumeRequest(BaseModel):
    extra_input: str = Field(..., min_length=1, description="사용자 추가 조건 / 힌트")
    max_rounds: int = Field(default=3, ge=1, le=10)
    persona: str | None = None  # 미지정 시 prev 유지
    use_rag: bool = True
    rag_collection: str = "budget"
    quality_profile: Literal["economy", "balanced", "quality"] = "balanced"
    auto_model_enabled: bool = False
    agent_backends: dict[str, str] = Field(default_factory=dict)
    use_web_search: bool = False
    save_obsidian: bool = True
