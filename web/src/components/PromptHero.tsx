"use client";
import { Paperclip, Globe, Hash, Sparkles, Square } from "lucide-react";
import { useRef } from "react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";

export function PromptHero() {
  const topic = useStore((s) => s.topic);
  const setTopic = useStore((s) => s.setTopic);
  const rounds = useStore((s) => s.rounds);
  const setRounds = useStore((s) => s.setRounds);
  const status = useStore((s) => s.status);
  const reset = useStore((s) => s.resetForRun);
  const setError = useStore((s) => s.setError);
  const pushMessage = useStore((s) => s.pushMessage);
  const setActiveRole = useStore((s) => s.setActiveRole);
  const setStatus = useStore((s) => s.setStatus);
  const setRound = useStore((s) => s.setRound);
  const setVerdict = useStore((s) => s.setVerdict);
  const setUsage = useStore((s) => s.setUsage);

  const useWeb = useStore((s) => s.useWeb);
  const useObsidian = useStore((s) => s.useObsidian);
  const profile = useStore((s) => s.profile);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const agentBackends = useStore((s) => s.agentBackends);
  const setWarning = useStore((s) => s.setWarning);
  const setResolvedBackends = useStore((s) => s.setResolvedBackends);

  const esRef = useRef<EventSource | null>(null);

  const stop = () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setStatus("idle");
    setActiveRole(null);
    setWarning("사용자가 토론을 중지했습니다.");
  };

  const start = async () => {
    if (!topic.trim() || status === "running" || status === "starting") return;
    reset();
    let agentMessageCount = 0;  // exclude the priming "user" prompt
    try {
      const { debate_id } = await api.start({
        topic: topic.trim(),
        debate_mode: mode,
        quality_profile: profile,
        max_rounds: rounds,
        use_web_search: useWeb,
        save_obsidian: useObsidian,
        agent_backends: agentBackends,
      });
      setStatus("running");
      const es = new EventSource(api.streamUrl(debate_id));
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data);
          if (d.type === "message") {
            pushMessage({
              id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
              role: d.role,
              speaker: d.speaker,
              content: d.content,
              round: d.round,
              model: d.model,
            });
            setActiveRole(d.role);
            // priming kickoff is role=user; real outputs are pro/con/judge/...
            if (d.role && d.role !== "user" && d.role !== "system") agentMessageCount++;
          } else if (d.type === "status") {
            if (d.stage === "round" && typeof d.round === "number") setRound(d.round);
            if (d.stage === "saving") setStatus("saving");
            if (d.stage === "resolved" && d.backends) setResolvedBackends(d.backends);
            if (d.stage === "error") setError(d.message || "error");
          } else if (d.type === "usage" && d.total) {
            // 누적 사용량 갱신 (delta는 서버에서 이미 더해짐)
            const cur = useStore.getState().usage;
            const role = d.role as string | undefined;
            const dlt = d.delta || {};
            const next_by_role = { ...cur.by_role } as any;
            if (role) {
              const prev = next_by_role[role] || { prompt: 0, completion: 0, cost_usd: 0 };
              next_by_role[role] = {
                prompt: prev.prompt + (dlt.prompt || 0),
                completion: prev.completion + (dlt.completion || 0),
                cost_usd: prev.cost_usd + (dlt.cost_usd || 0),
              };
            }
            setUsage({
              prompt: d.total.prompt ?? cur.prompt,
              completion: d.total.completion ?? cur.completion,
              cost_usd: d.total.cost_usd ?? cur.cost_usd,
              by_role: next_by_role,
            });
          } else if (d.type === "done") {
            setVerdict(d.verdict || "");
            if (typeof d.debate_id === "number") {
              useStore.getState().setLastDebateId(d.debate_id);
            }
            if (d.usage_total) {
              setUsage({
                prompt: d.usage_total.prompt || 0,
                completion: d.usage_total.completion || 0,
                cost_usd: d.usage_total.cost_usd || 0,
                by_role: d.usage_total.by_role || {},
              });
            }
            setStatus("done");
            setActiveRole(null);
            esRef.current = null;
            if (agentMessageCount === 0) {
              setWarning(
                "에이전트 응답이 비어있습니다. 무료 모델 한도 초과/네트워크 문제일 수 있습니다. 우측 패널에서 프로필을 '균형'으로 올리거나 [기본] 버튼으로 모델을 재설정 후 다시 시도해 주세요.",
              );
            } else if (agentMessageCount === 1) {
              setWarning(
                `에이전트 응답이 ${agentMessageCount}건만 수신되었습니다. 모델이 조기 종료했을 수 있습니다.`,
              );
            }
            es.close();
          }
        } catch (e) {
          console.error(e);
        }
      };
      es.onerror = () => {
        setStatus((status as any) === "saving" || (status as any) === "done" ? status : "error");
        es.close();
        esRef.current = null;
      };
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  };

  const statusChip = {
    idle: { label: "준비 완료", color: "#1D9E75" },
    starting: { label: "시작 중", color: "#D4A843" },
    running: { label: "토론 중", color: "#7F77DD" },
    saving: { label: "저장 중", color: "#378ADD" },
    done: { label: "완료", color: "#1D9E75" },
    error: { label: "오류", color: "#C94A4A" },
  }[status];

  return (
    <div className="px-6 py-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-from to-brand-to flex items-center justify-center text-white font-bold text-sm">
            GA
          </div>
          <div>
            <div className="text-ink-0 font-semibold text-[15px]">Debate Arena</div>
            <div className="text-ink-3 text-[12px]">· 다중 AI 토론 시스템</div>
          </div>
        </div>
        <div
          className="text-[12px] px-3 py-1 rounded-full font-medium"
          style={{ background: statusChip.color + "22", color: statusChip.color }}
        >
          ● {statusChip.label}
        </div>
      </div>

      <div className="text-ink-2 text-[13px] mb-2">무엇을 토론하시겠습니까?</div>
      <textarea
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        rows={2}
        placeholder="예) 연안정비사업의 수치모형실험 의무화가 타당한가?"
        className="w-full bg-bg-1 border border-default rounded-lg px-4 py-3 text-ink-0 text-[15px] leading-relaxed shadow-pop outline-none focus:border-brand-from focus:ring-2 focus:ring-brand-from/30"
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) start();
        }}
      />

      <div className="flex items-center justify-between mt-3 text-[12px]">
        <div className="flex items-center gap-3 text-ink-3">
          <button className="flex items-center gap-1 hover:text-ink-1"><Paperclip size={13} /> 문서</button>
          <button className="flex items-center gap-1 hover:text-ink-1"><Globe size={13} /> 웹검색</button>
          <button className="flex items-center gap-1 hover:text-ink-1"><Hash size={13} /> 태그</button>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="bg-bg-2 border border-subtle rounded-md text-[12px] text-ink-1 px-2 py-1 outline-none max-w-[160px]"
            title="토론 모드 선택"
          >
            {(useStore.getState().config?.modes || []).map((m: any) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
          <select
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
            className="bg-bg-2 border border-subtle rounded-md text-[12px] text-ink-1 px-2 py-1 outline-none"
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>{n} 라운드</option>
            ))}
          </select>
          {status === "running" || status === "starting" || status === "saving" ? (
            <button
              onClick={stop}
              className="flex items-center gap-1.5 bg-[#C94A4A] hover:bg-[#B53D3D] text-white px-4 py-1.5 rounded-md text-[13px] font-medium"
              title="진행 중인 토론 중지"
            >
              <Square size={12} fill="white" /> 중지
            </button>
          ) : (
            <button
              disabled={!topic.trim()}
              onClick={start}
              className="flex items-center gap-1.5 bg-gradient-to-br from-brand-from to-brand-to text-white px-4 py-1.5 rounded-md text-[13px] font-medium shadow-brand disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Sparkles size={13} /> 시작
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
