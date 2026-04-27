"use client";

import { useEffect, useRef, useState } from "react";
import { refineryApi, RefineryRunSummary } from "@/lib/api";

type StageKey =
  | "idle"
  | "starting"
  | "parse"
  | "align"
  | "transmute"
  | "critique"
  | "render"
  | "done"
  | "error"
  | "progress";

const STAGES: { key: StageKey; label: string }[] = [
  { key: "parse", label: "1. 정보 추출" },
  { key: "align", label: "2. 정책 정렬" },
  { key: "transmute", label: "3. 보고서 변환" },
  { key: "critique", label: "4. 자기 검수" },
];

interface DoneEvent {
  type: "done";
  run_id: number;
  report_md: string;
  alignment_intro: string;
  critique_md: string;
  citations: string[];
  replacements: Record<string, string>;
  model_log: Record<string, string>;
  error?: string;
}

export default function RefineryPage() {
  const [rawText, setRawText] = useState("");
  const [topic, setTopic] = useState("");
  const [sourceAi, setSourceAi] = useState("gemini");
  const [useWisdom, setUseWisdom] = useState(true);
  const [useAlignment, setUseAlignment] = useState(true);
  const [useCritique, setUseCritique] = useState(true);
  const [quality, setQuality] = useState<"economy" | "balanced" | "quality">("balanced");

  const [stage, setStage] = useState<StageKey>("idle");
  const [stageMsg, setStageMsg] = useState<string>("");
  const [logLines, setLogLines] = useState<string[]>([]);
  const [result, setResult] = useState<DoneEvent | null>(null);
  const [editedMd, setEditedMd] = useState("");
  const [saveMsg, setSaveMsg] = useState<string>("");
  const [runs, setRuns] = useState<RefineryRunSummary[]>([]);
  const esRef = useRef<EventSource | null>(null);

  const reachedStages: Set<StageKey> = (() => {
    const s = new Set<StageKey>();
    const order: StageKey[] = ["starting", "parse", "align", "transmute", "critique", "render", "done"];
    const idx = order.indexOf(stage);
    if (idx >= 0) order.slice(0, idx + 1).forEach((k) => s.add(k));
    return s;
  })();

  const loadRuns = async () => {
    try {
      const r = await refineryApi.runs();
      setRuns(r);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadRuns();
    return () => {
      esRef.current?.close();
    };
  }, []);

  const start = async () => {
    if (!rawText.trim() || !topic.trim()) {
      alert("주제와 원문은 필수입니다.");
      return;
    }
    setStage("starting");
    setStageMsg("");
    setLogLines([]);
    setResult(null);
    setEditedMd("");
    setSaveMsg("");
    esRef.current?.close();

    try {
      const { sid } = await refineryApi.start({
        raw_text: rawText,
        topic,
        source_ai: sourceAi,
        use_wisdom_rag: useWisdom,
        use_alignment: useAlignment,
        use_critique: useCritique,
        quality,
      });
      const es = new EventSource(refineryApi.streamUrl(sid));
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === "status") {
            setStage(data.stage as StageKey);
            if (data.message) {
              setStageMsg(data.message);
              setLogLines((l) => [...l, `[${data.stage}] ${data.message}`]);
            }
          } else if (data.type === "done") {
            setResult(data as DoneEvent);
            setEditedMd(data.report_md || "");
            setStage("done");
            es.close();
            esRef.current = null;
            loadRuns();
          }
        } catch (e) {
          console.error(e);
        }
      };
      es.onerror = () => {
        es.close();
        esRef.current = null;
      };
    } catch (e: any) {
      setStage("error");
      setStageMsg(String(e?.message || e));
    }
  };

  const save = async () => {
    if (!result || !editedMd.trim()) return;
    setSaveMsg("저장 중...");
    try {
      const r = await refineryApi.save({
        edited_md: editedMd,
        topic,
        critique_md: result.critique_md,
        citations: result.citations,
        run_id: result.run_id,
      });
      if (r.ok) {
        setSaveMsg(`저장 완료: ${r.obsidian_path || "(경로 미상)"}`);
        loadRuns();
      } else {
        setSaveMsg(`저장 실패: ${r.detail || "unknown"}`);
      }
    } catch (e: any) {
      setSaveMsg(`저장 오류: ${e?.message || e}`);
    }
  };

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] p-6">
      <div className="max-w-7xl mx-auto">
        <header className="mb-6 flex items-baseline gap-3">
          <h1 className="text-2xl font-bold">🧪 AI 정제소</h1>
          <span className="text-xs text-[#8b949e]">
            외부 AI 초안 → 4단계 정제 → 장안 브랜드 보고서
          </span>
          <a
            href="/"
            className="ml-auto text-xs text-[#58a6ff] hover:underline"
          >
            ← 토론 아레나
          </a>
        </header>

        <div className="grid grid-cols-12 gap-5">
          {/* 입력 패널 */}
          <section className="col-span-12 lg:col-span-4 space-y-4">
            <Card title="입력">
              <label className="block text-xs text-[#8b949e] mb-1">주제</label>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="예: 항만 노후 구조물 정비"
                className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm mb-3"
              />
              <label className="block text-xs text-[#8b949e] mb-1">원문 (외부 AI 초안)</label>
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                rows={14}
                placeholder="ChatGPT, Gemini 등에서 받아온 초안 전체 붙여넣기"
                className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm font-mono"
              />
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div>
                  <label className="block text-xs text-[#8b949e] mb-1">출처 AI</label>
                  <select
                    value={sourceAi}
                    onChange={(e) => setSourceAi(e.target.value)}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1.5 text-sm"
                  >
                    <option value="gemini">Gemini</option>
                    <option value="chatgpt">ChatGPT</option>
                    <option value="claude">Claude</option>
                    <option value="other">기타</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-[#8b949e] mb-1">품질</label>
                  <select
                    value={quality}
                    onChange={(e) => setQuality(e.target.value as any)}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1.5 text-sm"
                  >
                    <option value="economy">경제 (저비용)</option>
                    <option value="balanced">균형</option>
                    <option value="quality">최고 품질</option>
                  </select>
                </div>
              </div>
              <div className="mt-3 space-y-1.5">
                <Toggle label="지혜 RAG (장안 자료)" checked={useWisdom} onChange={setUseWisdom} />
                <Toggle label="정책 정렬 (상위계획 RAG)" checked={useAlignment} onChange={setUseAlignment} />
                <Toggle label="자기 검수 (4축)" checked={useCritique} onChange={setUseCritique} />
              </div>
              <button
                onClick={start}
                disabled={stage !== "idle" && stage !== "done" && stage !== "error"}
                className="mt-4 w-full py-2.5 rounded bg-[#238636] hover:bg-[#2ea043] disabled:opacity-50 disabled:cursor-not-allowed font-semibold text-sm"
              >
                {stage === "idle" || stage === "done" || stage === "error" ? "정제 시작" : "진행 중..."}
              </button>
            </Card>

            <Card title="이력">
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {runs.length === 0 && (
                  <div className="text-xs text-[#6e7681] py-2">아직 기록 없음</div>
                )}
                {runs.map((r) => (
                  <div
                    key={r.id}
                    className="text-xs border-b border-[#21262d] py-1.5 last:border-0"
                  >
                    <div className="text-[#c9d1d9] truncate">{r.topic}</div>
                    <div className="text-[#6e7681] flex justify-between">
                      <span>{r.created.slice(0, 16).replace("T", " ")}</span>
                      <span>{r.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </section>

          {/* 진행/결과 패널 */}
          <section className="col-span-12 lg:col-span-8 space-y-4">
            <Card title="진행 상황">
              <div className="grid grid-cols-4 gap-2 mb-3">
                {STAGES.map((s) => {
                  const active = stage === s.key;
                  const done = reachedStages.has(s.key) && !active;
                  const cls = active
                    ? "border-[#58a6ff] bg-[#0d1f3a] text-[#58a6ff]"
                    : done
                      ? "border-[#238636] bg-[#0a1f12] text-[#3fb950]"
                      : "border-[#30363d] text-[#6e7681]";
                  return (
                    <div
                      key={s.key}
                      className={`border rounded px-2 py-2 text-xs text-center ${cls}`}
                    >
                      {active && <span className="inline-block w-2 h-2 rounded-full bg-[#58a6ff] animate-pulse mr-1" />}
                      {done && <span className="mr-1">✓</span>}
                      {s.label}
                    </div>
                  );
                })}
              </div>
              {stageMsg && (
                <div className="text-xs text-[#8b949e] mb-2">{stageMsg}</div>
              )}
              {logLines.length > 0 && (
                <details className="text-xs">
                  <summary className="text-[#6e7681] cursor-pointer hover:text-[#c9d1d9]">
                    상세 로그 ({logLines.length})
                  </summary>
                  <div className="mt-2 max-h-40 overflow-y-auto font-mono text-[11px] bg-[#0d1117] border border-[#21262d] rounded p-2">
                    {logLines.map((l, i) => (
                      <div key={i} className="text-[#8b949e]">{l}</div>
                    ))}
                  </div>
                </details>
              )}
            </Card>

            {result && (
              <>
                <Card title="정제 결과 (편집 가능)">
                  <textarea
                    value={editedMd}
                    onChange={(e) => setEditedMd(e.target.value)}
                    rows={20}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm font-mono"
                  />
                  <div className="flex items-center gap-3 mt-3">
                    <button
                      onClick={save}
                      disabled={!editedMd.trim()}
                      className="px-4 py-2 rounded bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-sm font-semibold"
                    >
                      💾 Obsidian 저장
                    </button>
                    {saveMsg && (
                      <span className="text-xs text-[#8b949e]">{saveMsg}</span>
                    )}
                  </div>
                </Card>

                {result.critique_md && (
                  <Card title="🔎 자기 검수서">
                    <pre className="text-xs whitespace-pre-wrap font-mono text-[#c9d1d9]">
                      {result.critique_md}
                    </pre>
                  </Card>
                )}

                {result.citations && result.citations.length > 0 && (
                  <Card title="📚 참고 출처">
                    <ul className="text-xs space-y-1">
                      {result.citations.map((c, i) => (
                        <li key={i} className="text-[#8b949e]">• {c}</li>
                      ))}
                    </ul>
                  </Card>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-4">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-[#8b949e] mb-3">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-[#1f6feb]"
      />
      <span className="text-[#c9d1d9]">{label}</span>
    </label>
  );
}
