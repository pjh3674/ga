"use client";

import { useEffect, useState, useCallback } from "react";
import { systemApi, SystemStatusResponse, ServiceStatus, RagCollectionStat, opsApi, OpsMetricsResponse, DailyPoint, DailySummaryResponse, ModelCacheStatus, RefreshModelsResponse, ragApi, RagArchivedDoc } from "@/lib/api";

// ── 유틸 ─────────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const color =
    status === "healthy" ? "bg-emerald-400" :
    status === "degraded" ? "bg-yellow-400" : "bg-red-500";
  const pulse = status === "healthy" ? "animate-pulse" : "";
  return (
    <span className={`inline-block w-2.5 h-2.5 rounded-full ${color} ${pulse} mr-2`} />
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-[#161b22] border border-[#30363d] rounded-xl p-5 ${className}`}>
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-widest text-[#8b949e] mb-4">
      {children}
    </h2>
  );
}

// ── 서비스 카드 ───────────────────────────────────────────────────────────────

function ServiceCard({ svc }: { svc: ServiceStatus }) {
  const labelMap: Record<string, string> = {
    "ga-api": "GA API",
    "hwp-rag": "HWP-RAG",
    redis: "Redis",
  };
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#21262d] last:border-0">
      <div className="flex items-center gap-2">
        <StatusDot status={svc.status} />
        <span className="text-sm font-medium text-[#e6edf3]">{labelMap[svc.name] ?? svc.name}</span>
      </div>
      <span className="text-xs text-[#8b949e] truncate max-w-[160px]">{svc.detail || svc.status}</span>
    </div>
  );
}

// ── RAG 컬렉션 행 ─────────────────────────────────────────────────────────────

function RagRow({ col }: { col: RagCollectionStat }) {
  const pct = col.total_chunks > 0 ? Math.min(100, Math.round((col.total_documents / 200) * 100)) : 0;
  return (
    <div className="py-3 border-b border-[#21262d] last:border-0">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          {col.index_running && (
            <span className="text-[10px] bg-blue-900/60 text-blue-300 border border-blue-700 rounded px-1.5 py-0.5 font-medium">
              인덱싱 중
            </span>
          )}
          <span className="text-sm text-[#e6edf3] font-medium">{col.label}</span>
        </div>
        <div className="text-right">
          <span className="text-sm font-semibold text-[#58a6ff]">{col.total_chunks.toLocaleString()}</span>
          <span className="text-xs text-[#8b949e] ml-1">청크</span>
          <span className="text-xs text-[#8b949e] ml-2">({col.total_documents}문서)</span>
        </div>
      </div>
      <div className="w-full bg-[#21262d] rounded-full h-1.5">
        <div
          className="bg-gradient-to-r from-[#1f6feb] to-[#58a6ff] h-1.5 rounded-full transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── 토론 통계 ─────────────────────────────────────────────────────────────────

function DebateStats({ stats }: { stats: Record<string, unknown> }) {
  const items = [
    { label: "전체 토론", key: "total", color: "text-[#58a6ff]" },
    { label: "오늘", key: "today", color: "text-emerald-400" },
    { label: "이번 주", key: "this_week", color: "text-purple-400" },
  ];
  return (
    <div className="grid grid-cols-3 gap-3">
      {items.map(({ label, key, color }) => (
        <div key={key} className="bg-[#0d1117] rounded-lg p-3 text-center">
          <div className={`text-2xl font-bold ${color}`}>
            {String(stats[key] ?? "—")}
          </div>
          <div className="text-xs text-[#8b949e] mt-0.5">{label}</div>
        </div>
      ))}
    </div>
  );
}

// ── 운영 메트릭 — Sparkbar / KPI ─────────────────────────────────────────────

function SparkBar({
  data,
  field = "cnt",
  color = "#58a6ff",
  height = 56,
  unit = "",
}: {
  data: DailyPoint[];
  field?: "cnt" | "cost" | "p_tok" | "c_tok";
  color?: string;
  height?: number;
  unit?: string;
}) {
  const vals = data.map((d) => Number((d as any)[field] ?? 0));
  const max = Math.max(1, ...vals);
  const w = 22;
  const gap = 4;
  const totalW = data.length * (w + gap);
  return (
    <div className="overflow-x-auto">
      <svg width={Math.max(totalW, 100)} height={height + 18}>
        {data.map((d, i) => {
          const v = Number((d as any)[field] ?? 0);
          const h = Math.round((v / max) * height);
          const x = i * (w + gap);
          const y = height - h;
          return (
            <g key={d.day}>
              <rect x={x} y={y} width={w} height={h} fill={color} rx={2} />
              <text
                x={x + w / 2}
                y={y - 2}
                fontSize={9}
                fill="#8b949e"
                textAnchor="middle"
              >
                {field === "cost" ? `$${v.toFixed(3)}` : v}
              </text>
              <text
                x={x + w / 2}
                y={height + 12}
                fontSize={9}
                fill="#6e7681"
                textAnchor="middle"
              >
                {d.day.slice(5)}
              </text>
            </g>
          );
        })}
      </svg>
      {unit && <div className="text-[10px] text-[#6e7681] mt-1">단위: {unit}</div>}
    </div>
  );
}

function KPI({ label, value, color = "text-[#e6edf3]" }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="bg-[#0d1117] rounded-lg p-3 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-[#8b949e] mt-0.5">{label}</div>
    </div>
  );
}

// ── RAG 아카이브 관리 패널 ────────────────────────────────────────────────────
function ArchivedPanel({ collections }: { collections: RagCollectionStat[] }) {
  const names = collections.map((c) => c.name);
  const [open, setOpen] = useState(false);
  const [collection, setCollection] = useState<string>(names[0] || "wisdom_base");
  const [items, setItems] = useState<RagArchivedDoc[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<string>("");

  useEffect(() => {
    if (!collection && names.length) setCollection(names[0]);
  }, [names.join(","), collection]);

  const load = async (col: string) => {
    setLoading(true); setErr("");
    try {
      const r = await ragApi.listArchived(col);
      setItems(r.items);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && collection) load(collection);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, collection]);

  const unarchive = async (filepath: string) => {
    setBusy(filepath);
    try {
      const r = await ragApi.setArchived(collection, filepath, false);
      if (!r.ok) { setErr(r.error || "복원 실패"); return; }
      setItems((prev) => (prev || []).filter((x) => x.filepath !== filepath));
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="mt-4 pt-3 border-t border-[#21262d]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-[#58a6ff] hover:underline"
      >
        {open ? "▼" : "▶"} 아카이브된 문서 관리
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-2 text-xs">
            <label className="text-[#8b949e]">컬렉션</label>
            <select
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-[#e6edf3]"
            >
              {(names.length ? names : ["wisdom_base"]).map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
            <button
              onClick={() => load(collection)}
              disabled={loading}
              className="px-2 py-1 rounded bg-[#21262d] hover:bg-[#30363d] disabled:opacity-50"
            >
              {loading ? "로딩…" : "새로고침"}
            </button>
            {items && (
              <span className="text-[#8b949e]">총 {items.length}개</span>
            )}
            {err && <span className="text-red-400">⚠ {err}</span>}
          </div>
          {items && items.length === 0 ? (
            <div className="text-xs text-[#8b949e] italic">아카이브된 문서가 없습니다.</div>
          ) : (
            <div className="max-h-80 overflow-auto border border-[#21262d] rounded">
              <table className="w-full text-xs">
                <thead className="bg-[#0d1117] sticky top-0">
                  <tr className="text-left text-[#8b949e]">
                    <th className="px-2 py-1.5">파일경로</th>
                    <th className="px-2 py-1.5 text-right">청크</th>
                    <th className="px-2 py-1.5 text-right">동작</th>
                  </tr>
                </thead>
                <tbody>
                  {(items || []).map((it) => (
                    <tr key={it.filepath} className="border-t border-[#21262d] hover:bg-[#0d1117]">
                      <td className="px-2 py-1.5 font-mono text-[#e6edf3] break-all">
                        {it.title ? <span className="text-[#a5d6ff]">{it.title} · </span> : null}
                        {it.filepath}
                      </td>
                      <td className="px-2 py-1.5 text-right text-[#8b949e]">{it.chunk_count || "—"}</td>
                      <td className="px-2 py-1.5 text-right">
                        <button
                          onClick={() => unarchive(it.filepath)}
                          disabled={busy === it.filepath}
                          className="px-2 py-0.5 rounded bg-emerald-900/40 hover:bg-emerald-900/60 text-emerald-300 disabled:opacity-50"
                        >
                          {busy === it.filepath ? "…" : "복원"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────

export default function StatusPage() {
  const [data, setData] = useState<SystemStatusResponse | null>(null);
  const [ops, setOps] = useState<OpsMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summary, setSummary] = useState<DailySummaryResponse | null>(null);
  const [summaryErr, setSummaryErr] = useState<string | null>(null);
  const [modelCache, setModelCache] = useState<ModelCacheStatus | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshResult, setRefreshResult] = useState<RefreshModelsResponse | null>(null);

  const fetch = useCallback(() => {
    setLoading(true);
    Promise.all([systemApi.status(), opsApi.metrics(7), opsApi.modelCacheStatus()])
      .then(([d, o, mc]) => { setData(d); setOps(o); setModelCache(mc); setError(null); setLastRefresh(new Date()); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // 초기 로드 + 30초 자동 갱신
  useEffect(() => {
    fetch();
    const id = setInterval(fetch, 30_000);
    return () => clearInterval(id);
  }, [fetch]);

  const nasStatus = data?.nas_ok ? "healthy" : data ? "down" : "degraded";

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#e6edf3] p-6 md:p-10">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-[#e6edf3]">
            🏛️ 항만연안재생과 AI 관제실
          </h1>
          <p className="text-xs text-[#8b949e] mt-0.5">
            {lastRefresh
              ? `마지막 갱신: ${lastRefresh.toLocaleTimeString("ko-KR")}`
              : "데이터 로딩 중..."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-[#8b949e] animate-pulse">갱신 중...</span>
          )}
          <button
            onClick={fetch}
            className="text-xs bg-[#21262d] hover:bg-[#30363d] border border-[#30363d] text-[#c9d1d9] rounded-lg px-3 py-1.5 transition-colors"
          >
            ↻ 새로고침
          </button>
          <button
            onClick={async () => {
              setSummaryBusy(true); setSummaryErr(null); setSummary(null);
              try {
                const res = await opsApi.dailySummary();
                setSummary(res);
              } catch (e: any) {
                setSummaryErr(e?.message ?? String(e));
              } finally {
                setSummaryBusy(false);
              }
            }}
            disabled={summaryBusy}
            className="text-xs bg-[#238636] hover:bg-[#2ea043] disabled:opacity-50 text-white rounded-lg px-3 py-1.5 transition-colors"
            title="어제자의 토론/정제소 요약을 Obsidian Daily Note에 prepend"
          >
            {summaryBusy ? "… 생성 중" : "📝 어제 요약 생성"}
          </button>
          <a
            href="/"
            className="text-xs bg-[#1f6feb] hover:bg-[#388bfd] text-white rounded-lg px-3 py-1.5 transition-colors"
          >
            토론 아레나 →
          </a>
        </div>
      </div>

      {error && (
        <div className="mb-6 bg-red-950/40 border border-red-800 rounded-xl p-4 text-sm text-red-300">
          ⚠️ API 오류: {error}
        </div>
      )}

      {summaryErr && (
        <div className="mb-6 bg-red-950/40 border border-red-800 rounded-xl p-4 text-sm text-red-300">
          📝 요약 생성 실패: {summaryErr}
        </div>
      )}

      {summary && (
        <div className="mb-6 bg-[#161b22] border border-[#30363d] rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-[#e6edf3]">
              📝 일일 요약 — {summary.date}
            </div>
            <button
              onClick={() => setSummary(null)}
              className="text-xs text-[#8b949e] hover:text-[#e6edf3]"
            >✕</button>
          </div>
          <div className="text-xs text-[#8b949e] space-y-1 mb-3">
            <div>
              Daily Note: {summary.daily_note.ok ? "✅" : "❌"}{" "}
              <span className="font-mono text-[#c9d1d9]">{summary.daily_note.path}</span>
              {summary.daily_note.error && <span className="text-red-400"> ({summary.daily_note.error})</span>}
            </div>
            <div>
              보관노트: {summary.archive.ok ? "✅" : "❌"}{" "}
              <span className="font-mono text-[#c9d1d9]">{summary.archive.path || "-"}</span>
              {summary.archive.error && <span className="text-red-400"> ({summary.archive.error})</span>}
            </div>
          </div>
          <pre className="text-[11px] bg-[#0d1117] rounded-lg p-3 max-h-72 overflow-auto whitespace-pre-wrap text-[#c9d1d9]">
{summary.summary_markdown}
          </pre>
        </div>
      )}

      {/* 2열 그리드 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

        {/* 서비스 상태 */}
        <Card>
          <SectionTitle>서비스 상태</SectionTitle>
          {data ? (
            <div>
              {data.services.map((s) => <ServiceCard key={s.name} svc={s} />)}
              {/* NAS */}
              <div className="flex items-center justify-between py-2.5 border-b border-[#21262d] last:border-0">
                <div className="flex items-center gap-2">
                  <StatusDot status={nasStatus} />
                  <span className="text-sm font-medium text-[#e6edf3]">NAS (DS925+)</span>
                </div>
                <span className="text-xs text-[#8b949e] truncate max-w-[160px]">
                  {data.nas_detail || (data.nas_ok ? "정상" : "연결 불가")}
                </span>
              </div>
            </div>
          ) : (
            <div className="animate-pulse space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-8 bg-[#21262d] rounded" />
              ))}
            </div>
          )}
        </Card>

        {/* 토론 통계 */}
        <Card>
          <SectionTitle>토론 통계</SectionTitle>
          {data ? (
            <DebateStats stats={data.debate_stats} />
          ) : (
            <div className="animate-pulse h-24 bg-[#21262d] rounded" />
          )}
        </Card>

        {/* RAG 지식베이스 — 전체 너비 */}
        <Card className="md:col-span-2">
          <SectionTitle>RAG 지식베이스</SectionTitle>
          {data?.rag_collections.length ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8">
              {data.rag_collections.map((col) => (
                <RagRow key={col.name} col={col} />
              ))}
            </div>
          ) : (
            <div className="animate-pulse space-y-4">
              {[1, 2, 3].map((i) => <div key={i} className="h-10 bg-[#21262d] rounded" />)}
            </div>
          )}
          {data && (
            <div className="mt-4 pt-3 border-t border-[#21262d] flex gap-6 text-xs text-[#8b949e]">
              <span>
                총 문서:{" "}
                <strong className="text-[#e6edf3]">
                  {data.rag_collections.reduce((s, c) => s + c.total_documents, 0).toLocaleString()}
                </strong>
              </span>
              <span>
                총 청크:{" "}
                <strong className="text-[#e6edf3]">
                  {data.rag_collections.reduce((s, c) => s + c.total_chunks, 0).toLocaleString()}
                </strong>
              </span>
              <span>
                인덱싱 중:{" "}
                <strong className="text-yellow-400">
                  {data.rag_collections.filter((c) => c.index_running).length}개
                </strong>
              </span>
            </div>
          )}
          <ArchivedPanel collections={data?.rag_collections || []} />
        </Card>

      </div>

      {/* ── Phase 3: 운영 메트릭 ───────────────────────────────────── */}
      {ops && (
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-5">
          <Card className="md:col-span-2">
            <SectionTitle>최근 {ops.window_days}일 운영 추세</SectionTitle>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <div className="text-xs text-[#8b949e] mb-2">📊 일별 토론 수</div>
                {ops.debates_daily.length ? (
                  <SparkBar data={ops.debates_daily} field="cnt" color="#58a6ff" />
                ) : (
                  <div className="text-xs text-[#6e7681] py-4">데이터 없음</div>
                )}
              </div>
              <div>
                <div className="text-xs text-[#8b949e] mb-2">🧪 일별 정제소 실행</div>
                {ops.refinery_daily.length ? (
                  <SparkBar data={ops.refinery_daily} field="cnt" color="#3fb950" />
                ) : (
                  <div className="text-xs text-[#6e7681] py-4">데이터 없음</div>
                )}
              </div>
              <div>
                <div className="text-xs text-[#8b949e] mb-2">💰 일별 비용 (USD)</div>
                {ops.cost_daily.length ? (
                  <SparkBar data={ops.cost_daily} field="cost" color="#f0883e" />
                ) : (
                  <div className="text-xs text-[#6e7681] py-4">기록 없음 (token_usage 미사용)</div>
                )}
              </div>
            </div>
          </Card>

          <Card>
            <SectionTitle>🧵 토론 스레드 (Resume)</SectionTitle>
            <div className="grid grid-cols-3 gap-3">
              <KPI label="총 스레드" value={ops.thread_total} color="text-[#58a6ff]" />
              <KPI label="이어가기 발생" value={ops.threads_with_resume} color="text-emerald-400" />
              <KPI label="최대 라운드" value={ops.max_rounds_in_thread} color="text-purple-400" />
            </div>
            <div className="mt-3 text-[11px] text-[#6e7681]">
              "이어가기 발생"은 같은 thread_id에 토론이 2회 이상 누적된 경우입니다.
            </div>
          </Card>

          <Card>
            <SectionTitle>🧪 정제소 상태</SectionTitle>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <KPI label="전체 실행" value={ops.refinery_total} color="text-[#58a6ff]" />
              <KPI
                label="완료율"
                value={
                  ops.refinery_total === 0
                    ? "—"
                    : `${Math.round(
                        ((ops.refinery_by_status.find((s) => s.status === "completed")?.cnt ?? 0) /
                          ops.refinery_total) *
                          100,
                      )}%`
                }
                color="text-emerald-400"
              />
            </div>
            <div className="space-y-1.5">
              {ops.refinery_by_status.length === 0 && (
                <div className="text-xs text-[#6e7681] py-2">상태 정보 없음</div>
              )}
              {ops.refinery_by_status.map((s) => {
                const color =
                  s.status === "completed"
                    ? "text-emerald-400"
                    : s.status === "failed"
                      ? "text-red-400"
                      : s.status === "pending"
                        ? "text-yellow-400"
                        : "text-[#8b949e]";
                return (
                  <div key={s.status} className="flex justify-between text-xs">
                    <span className={color}>{s.status}</span>
                    <span className="text-[#c9d1d9]">{s.cnt}건</span>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card className="md:col-span-2">
            <SectionTitle>💰 비용 상위 모델 (누적)</SectionTitle>
            {ops.top_cost_models.length === 0 ? (
              <div className="text-xs text-[#6e7681] py-4">
                아직 token_usage 기록이 없습니다. (debate.py에서 log_token_usage 호출 시 누적)
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[#6e7681] border-b border-[#21262d]">
                    <th className="text-left py-2 font-medium">모델</th>
                    <th className="text-right py-2 font-medium">호출</th>
                    <th className="text-right py-2 font-medium">누적 비용 (USD)</th>
                  </tr>
                </thead>
                <tbody>
                  {ops.top_cost_models.map((m) => (
                    <tr key={m.model} className="border-b border-[#21262d] last:border-0">
                      <td className="py-2 text-[#c9d1d9] font-mono">{m.model}</td>
                      <td className="py-2 text-right text-[#8b949e]">{m.calls}</td>
                      <td className="py-2 text-right text-[#f0883e] font-semibold">
                        ${(m.cost ?? 0).toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}

      {/* ── Phase 5: 모델 캐시 관제 ──────────────────── */}
      {modelCache && (
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-5">
          <Card className="md:col-span-2">
            <div className="flex items-center justify-between mb-3">
              <SectionTitle>🪙 모델 캐시 최적화 (Phase 5)</SectionTitle>
              <button
                onClick={async () => {
                  setRefreshBusy(true); setRefreshResult(null);
                  try {
                    const r = await opsApi.refreshModels();
                    setRefreshResult(r);
                    if (r.status) setModelCache(r.status);
                  } catch (e: any) {
                    setRefreshResult({ ok: false, elapsed_sec: 0, log_tail: "", error: e?.message ?? String(e), status: null });
                  } finally {
                    setRefreshBusy(false);
                  }
                }}
                disabled={refreshBusy}
                className="text-xs bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-white rounded-lg px-3 py-1.5 transition-colors"
                title="OpenRouter에서 최신 모델 리스트 수집 + 가중치 자동 튜닝"
              >
                {refreshBusy ? "… 갱신 중" : "↻ 지금 갱신"}
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <KPI label="무료 모델" value={modelCache.free_count} color="text-emerald-400" />
              <KPI label="유료 후보" value={modelCache.paid_count} color="text-[#f0883e]" />
              <KPI label="정제 총수" value={modelCache.cleaned_total} color="text-[#58a6ff]" />
              <KPI
                label="캐시 나이"
                value={modelCache.age_minutes == null ? "—" : modelCache.age_minutes < 60 ? `${modelCache.age_minutes}분` : `${Math.floor(modelCache.age_minutes / 60)}시간`}
                color={modelCache.age_minutes != null && modelCache.age_minutes > 60 * 36 ? "text-red-400" : "text-[#c9d1d9]"}
              />
            </div>
            <div className="text-[11px] text-[#8b949e] mb-2">
              마지막 갱신: <span className="font-mono text-[#c9d1d9]">{modelCache.updated_at || "—"}</span>
              {modelCache.age_minutes != null && modelCache.age_minutes > 60 * 36 && (
                <span className="ml-2 text-red-400">⚠️ 36시간 경과 — 갱신 권장</span>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-[#8b949e] mb-1.5">역할별 무료 기본 배정</div>
                <div className="space-y-1">
                  {Object.entries(modelCache.default_per_role).length === 0 ? (
                    <div className="text-xs text-[#6e7681]">캐시 없음 — "지금 갱신" 클릭</div>
                  ) : (
                    Object.entries(modelCache.default_per_role).map(([role, mid]) => (
                      <div key={role} className="flex justify-between text-[11px] border-b border-[#21262d] pb-1">
                        <span className="text-[#8b949e]">{role}</span>
                        <span className="font-mono text-[#c9d1d9] truncate ml-2" title={mid}>{mid}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                <div className="text-xs text-[#8b949e] mb-1.5">최근 가중치 튜닝</div>
                {modelCache.weight_changes.length === 0 ? (
                  <div className="text-xs text-[#6e7681] py-2">표본 부족 또는 안정 — 조정 없음</div>
                ) : (
                  <ul className="text-[11px] text-[#c9d1d9] space-y-0.5">
                    {modelCache.weight_changes.map((c, i) => (
                      <li key={i} className="font-mono">• {c}</li>
                    ))}
                  </ul>
                )}
                <div className="mt-2 text-[10px] text-[#6e7681]">
                  프로필: {modelCache.profiles.join(" · ") || "—"}
                </div>
              </div>
            </div>
            {refreshResult && (
              <div className="mt-4 border-t border-[#21262d] pt-3">
                <div className="text-xs mb-1">
                  {refreshResult.ok ? "✅" : "❌"} 갱신 결과 · {refreshResult.elapsed_sec}s
                  {refreshResult.error && <span className="text-red-400 ml-2">{refreshResult.error}</span>}
                </div>
                {refreshResult.log_tail && (
                  <pre className="text-[10px] bg-[#0d1117] rounded p-2 max-h-48 overflow-auto whitespace-pre-wrap text-[#8b949e]">{refreshResult.log_tail}</pre>
                )}
              </div>
            )}
          </Card>
        </div>
      )}

      <p className="mt-8 text-center text-xs text-[#484f58]">
        30초마다 자동 갱신 · GA Debate Arena v7.0
      </p>
    </div>
  );
}
