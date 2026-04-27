"use client";
import { AgentGraph } from "./AgentGraph";
import { MessageList } from "./MessageList";
import { PromptHero } from "./PromptHero";
import { ResumePanel } from "./ResumePanel";
import { useStore } from "@/lib/store";

export function Arena() {
  const status = useStore((s) => s.status);
  const round = useStore((s) => s.currentRound);
  const verdict = useStore((s) => s.verdict);
  const error = useStore((s) => s.errorMsg);
  const warning = useStore((s) => s.warning);
  const setWarning = useStore((s) => s.setWarning);

  const subtitle =
    status === "running" || status === "starting"
      ? `Round ${round || 1} · 진행 중`
      : status === "saving"
        ? "저장 중"
        : status === "done"
          ? "완료"
          : "Opening statements";

  return (
    <main className="flex flex-col h-full bg-bg-0 overflow-hidden">
      <div className="shrink-0">
        <PromptHero />
      </div>

      <div className="shrink-0 px-6 py-3 border-t border-subtle">
        <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium mb-2">
          LIVE ARENA
        </div>
        <div className="flex items-center justify-center min-h-[280px]">
          <AgentGraph />
        </div>
        <div className="text-center text-[12px] text-ink-3 mt-1">{subtitle}</div>
      </div>

      <div className="flex-1 overflow-y-auto" style={{ minHeight: 0 }}>
        <MessageList />

        {verdict && (
          <div className="mx-6 my-4 p-4 bg-bg-1 border border-default rounded-lg">
            <div className="text-[11px] uppercase tracking-wider text-agent-judge font-medium mb-2">
              ⚖️ JUDGE VERDICT
            </div>
            <div className="text-[13px] text-ink-1 whitespace-pre-wrap">{verdict}</div>
          </div>
        )}

        <ResumePanel />

        {warning && (
          <div className="mx-6 my-3 p-3 bg-yellow-950/30 border border-yellow-700/40 rounded-lg text-[13px] text-yellow-200 flex items-start gap-3">
            <span className="text-yellow-400">⚠️</span>
            <div className="flex-1 leading-relaxed">{warning}</div>
            <button
              onClick={() => setWarning(null)}
              className="text-yellow-400/70 hover:text-yellow-300 text-[12px] shrink-0"
            >
              닫기
            </button>
          </div>
        )}

        {error && (
          <div className="mx-6 my-4 p-3 bg-red-950/40 border border-red-800/50 rounded-lg text-[13px] text-red-300">
            {error}
          </div>
        )}
      </div>
    </main>
  );
}
