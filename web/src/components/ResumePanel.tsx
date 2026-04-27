"use client";

import { useRef, useState } from "react";
import { Plus, Square } from "lucide-react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";

/**
 * 토론 종료 후 노출되는 "추가 조건 입력 + 이어가기" 패널.
 * verdict가 존재하고 lastDebateId가 있을 때만 표시.
 *
 * 기존 메시지는 그대로 유지하고, 구분선 메시지를 push한 후 새 라운드를 SSE로 받는다.
 */
export function ResumePanel() {
  const verdict = useStore((s) => s.verdict);
  const lastDebateId = useStore((s) => s.lastDebateId);
  const status = useStore((s) => s.status);
  const profile = useStore((s) => s.profile);
  const useObsidian = useStore((s) => s.useObsidian);
  const agentBackends = useStore((s) => s.agentBackends);

  const resetForResume = useStore((s) => s.resetForResume);
  const pushMessage = useStore((s) => s.pushMessage);
  const setActiveRole = useStore((s) => s.setActiveRole);
  const setStatus = useStore((s) => s.setStatus);
  const setRound = useStore((s) => s.setRound);
  const setVerdict = useStore((s) => s.setVerdict);
  const setUsage = useStore((s) => s.setUsage);
  const setError = useStore((s) => s.setError);
  const setWarning = useStore((s) => s.setWarning);
  const setLastDebateId = useStore((s) => s.setLastDebateId);

  const [extraInput, setExtraInput] = useState("");
  const [extraRounds, setExtraRounds] = useState(3);
  const esRef = useRef<EventSource | null>(null);

  const busy = status === "starting" || status === "running" || status === "saving";

  if (!verdict || !lastDebateId) return null;

  const stop = () => {
    esRef.current?.close();
    esRef.current = null;
    setStatus("idle");
    setActiveRole(null);
    setWarning("사용자가 추가 라운드를 중지했습니다.");
  };

  const start = async () => {
    if (!extraInput.trim() || busy) return;
    const baseId = lastDebateId;
    resetForResume();
    pushMessage({
      id: `sep-${Date.now()}`,
      role: "system",
      speaker: "── 추가 조건 적용 ──",
      content: `🔁 이어가기 (Round +${extraRounds})\n조건: ${extraInput.trim()}`,
    });

    try {
      const { debate_id: sid } = await api.resume(baseId, {
        extra_input: extraInput.trim(),
        max_rounds: extraRounds,
        quality_profile: profile as any,
        use_rag: true,
        save_obsidian: useObsidian,
        agent_backends: agentBackends as Record<string, string>,
      });

      setStatus("running");
      const es = new EventSource(api.streamUrl(sid));
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
          } else if (d.type === "status") {
            if (d.stage === "round" && typeof d.round === "number") setRound(d.round);
            if (d.stage === "saving") setStatus("saving");
            if (d.stage === "error") setError(d.message || "error");
          } else if (d.type === "usage" && d.total) {
            setUsage({
              prompt: d.total.prompt ?? 0,
              completion: d.total.completion ?? 0,
              cost_usd: d.total.cost_usd ?? 0,
              by_role: useStore.getState().usage.by_role,
            });
          } else if (d.type === "done") {
            setVerdict(d.verdict || "");
            if (typeof d.debate_id === "number") setLastDebateId(d.debate_id);
            setStatus("done");
            setActiveRole(null);
            esRef.current = null;
            setExtraInput("");
            es.close();
          }
        } catch (e) {
          console.error(e);
        }
      };
      es.onerror = () => {
        setStatus(useStore.getState().status === "saving" || useStore.getState().status === "done"
          ? useStore.getState().status
          : "error");
        es.close();
        esRef.current = null;
      };
    } catch (e: any) {
      setError(String(e?.message || e));
    }
  };

  return (
    <div className="mx-6 mb-4 p-4 bg-bg-1 border border-default rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium">
          🔁 추가 조건으로 이어가기
        </div>
        <div className="text-[11px] text-ink-3">
          이전 토론 #{lastDebateId} · verdict 컨텍스트 유지
        </div>
      </div>

      <textarea
        value={extraInput}
        onChange={(e) => setExtraInput(e.target.value)}
        placeholder='예) "예산 100억을 추가로 확보했다고 가정. 인력 1명 충원 가능. 이 조건에서 결론이 어떻게 바뀌나?"'
        rows={3}
        disabled={busy}
        className="w-full bg-bg-0 border border-subtle rounded px-3 py-2 text-[13px] text-ink-1 resize-y disabled:opacity-50"
      />

      <div className="flex items-center gap-3 mt-3">
        <label className="text-[12px] text-ink-2 flex items-center gap-2">
          추가 라운드
          <input
            type="number"
            min={1}
            max={10}
            value={extraRounds}
            onChange={(e) => setExtraRounds(Math.max(1, Math.min(10, Number(e.target.value) || 3)))}
            disabled={busy}
            className="w-14 bg-bg-0 border border-subtle rounded px-2 py-1 text-[12px] text-ink-1 disabled:opacity-50"
          />
        </label>

        {busy ? (
          <button
            onClick={stop}
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-red-900/40 hover:bg-red-900/60 border border-red-800/60 text-[13px] text-red-200"
          >
            <Square size={13} /> 중지
          </button>
        ) : (
          <button
            onClick={start}
            disabled={!extraInput.trim()}
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed text-[13px] text-white font-medium"
          >
            <Plus size={13} /> 이어가기
          </button>
        )}
      </div>
    </div>
  );
}
