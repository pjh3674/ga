export type Role = "pro" | "con" | "judge" | "fact" | "audience";

export interface Profile { id: string; label: string }
export interface Mode { id: string; label: string; icon?: string }
export interface ModelOption { key: string; label: string; provider: "free" | "openrouter" | "static" }
export interface ConfigBundle {
  profiles: Profile[];
  modes: Mode[];
  backends: ModelOption[];
  recommended: Partial<Record<Role, string>>;
  personas: Record<string, string>;
}

export interface ArchiveItem {
  id: number; topic: string; created: string; summary: string; verdict: string; debate_mode: string;
  thread_id?: number | null;
}
export interface ArchiveGroup { label: string; items: ArchiveItem[] }

export interface DebateMessage {
  id: string;
  role: string;       // pro | con | judge | fact | audience | system
  speaker: string;
  content: string;
  round?: number;
  model?: string;
}

const J = (r: Response) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const api = {
  config: (profile = "balanced"): Promise<ConfigBundle> =>
    fetch(`/api/config?profile=${encodeURIComponent(profile)}`).then(J),
  defaults: (): Promise<Partial<Record<Role, string>>> => fetch("/api/defaults").then(J),
  list: (): Promise<ArchiveGroup[]> => fetch("/api/debates").then(J),
  get: (id: number) => fetch(`/api/debates/${id}`).then(J),
  start: (req: any): Promise<{ debate_id: string }> =>
    fetch("/api/debates/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
    }).then(J),
  resume: (debateId: number, req: {
    extra_input: string;
    max_rounds?: number;
    persona?: string;
    use_rag?: boolean;
    rag_collection?: string;
    quality_profile?: "economy" | "balanced" | "quality";
    auto_model_enabled?: boolean;
    agent_backends?: Record<string, string>;
    use_web_search?: boolean;
    save_obsidian?: boolean;
  }): Promise<{ debate_id: string }> =>
    fetch(`/api/debates/${debateId}/resume`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
    }).then(J),
  streamUrl: (sid: string) => `/api/debates/run/${sid}/stream`,
};

// ── System Status ──────────────────────────────────────────────────────
export interface RagCollectionStat {
  name: string;
  label: string;
  total_documents: number;
  total_chunks: number;
  index_running: boolean;
}

export interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "down";
  detail: string;
}

export interface SystemStatusResponse {
  timestamp: string;
  rag_collections: RagCollectionStat[];
  services: ServiceStatus[];
  debate_stats: Record<string, unknown>;
  nas_ok: boolean;
  nas_detail: string;
}

export const systemApi = {
  status: (): Promise<SystemStatusResponse> =>
    fetch("/api/system-status").then(J),
};

// ── Ops Metrics (Phase 3) ──────────────────────────────────────────
export interface DailyPoint {
  day: string;
  cnt?: number;
  cost?: number;
  p_tok?: number;
  c_tok?: number;
}
export interface TopCostModel { model: string; cost: number; calls: number; }
export interface StatusCount { status: string; cnt: number; }
export interface OpsMetricsResponse {
  window_days: number;
  debates_daily: DailyPoint[];
  refinery_daily: DailyPoint[];
  cost_daily: DailyPoint[];
  refinery_by_status: StatusCount[];
  refinery_total: number;
  thread_total: number;
  threads_with_resume: number;
  max_rounds_in_thread: number;
  top_cost_models: TopCostModel[];
}

export const opsApi = {
  metrics: (days = 7): Promise<OpsMetricsResponse> =>
    fetch(`/api/ops-metrics?days=${days}`).then(J),
  dailySummary: (date?: string): Promise<DailySummaryResponse> =>
    fetch("/api/ops/daily-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: date ?? null }),
    }).then(J),
  modelCacheStatus: (): Promise<ModelCacheStatus> =>
    fetch("/api/ops/model-cache-status").then(J),
  refreshModels: (): Promise<RefreshModelsResponse> =>
    fetch("/api/ops/refresh-models", { method: "POST" }).then(J),
};

// ── Daily Summary (Phase 4) ───────────────────────────────────────
export interface DailySummaryTarget { ok: boolean; path: string; error: string; }
export interface DailySummaryResponse {
  date: string;
  summary_markdown: string;
  daily_note: DailySummaryTarget;
  archive: DailySummaryTarget;
}

// ── Model Cache (Phase 5) ──────────────────────────────────────────
export interface ModelCacheStatus {
  updated_at: string;
  schema_version: number;
  free_count: number;
  paid_count: number;
  cleaned_total: number;
  weight_changes: string[];
  default_per_role: Record<string, string>;
  auto_recommended: string;
  profiles: string[];
  age_minutes: number | null;
}
export interface RefreshModelsResponse {
  ok: boolean;
  elapsed_sec: number;
  log_tail: string;
  error: string;
  status: ModelCacheStatus | null;
}

// ── RAG 아카이브 (Phase 1-1) ─────────────────────────────────────────
export interface RagArchivedDoc { filepath: string; title: string; chunk_count: number; }
export interface RagArchiveListResponse { collection: string; items: RagArchivedDoc[]; }

export const ragApi = {
  listArchived: (collection = "wisdom_base"): Promise<RagArchiveListResponse> =>
    fetch(`/api/rag/archived?collection=${encodeURIComponent(collection)}`).then(J),
  setArchived: (collection: string, filepath: string, archived: boolean): Promise<{ok: boolean; error: string}> =>
    fetch("/api/rag/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collection, filepath, archived }),
    }).then(J),
};

// ── Refinery (Phase 2) ───────────────────────────────────────────────
export interface RefineryStartRequest {
  raw_text: string;
  topic: string;
  source_ai?: string;
  template_id?: string;
  use_wisdom_rag?: boolean;
  use_alignment?: boolean;
  use_critique?: boolean;
  quality?: "economy" | "balanced" | "quality";
  backend_key?: string;
}

export interface RefineryRunSummary {
  id: number;
  topic: string;
  created: string;
  source_ai: string;
  template_id: string;
  status: string;
}

export interface RefinerySaveResponse {
  ok: boolean;
  obsidian_path: string | null;
  run_id: number;
  detail: string;
}

export const refineryApi = {
  start: (req: RefineryStartRequest): Promise<{ sid: string }> =>
    fetch("/api/refinery/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
    }).then(J),
  streamUrl: (sid: string) => `/api/refinery/run/${sid}/stream`,
  save: (body: {
    edited_md: string;
    topic: string;
    critique_md?: string;
    citations?: string[];
    run_id?: number;
  }): Promise<RefinerySaveResponse> =>
    fetch("/api/refinery/save", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(J),
  runs: (): Promise<RefineryRunSummary[]> =>
    fetch("/api/refinery/runs").then(J),
};
