"use client";
import { useStore } from "@/lib/store";
import { api, Role } from "@/lib/api";
import { Wand2, Sparkles } from "lucide-react";
import clsx from "clsx";

const ROLE_META: { id: Role; label: string; icon: string; color: string }[] = [
  { id: "pro", label: "찬성", icon: "🟢", color: "#97C459" },
  { id: "con", label: "반대", icon: "🔴", color: "#E24B4A" },
  { id: "judge", label: "심판", icon: "⚖️", color: "#EF9F27" },
  { id: "fact", label: "팩트", icon: "🔍", color: "#378ADD" },
  { id: "audience", label: "청중", icon: "👥", color: "#7F77DD" },
];

export function RightPanel() {
  const config = useStore((s) => s.config);
  const profile = useStore((s) => s.profile);
  const setProfile = useStore((s) => s.setProfile);
  const setConfig = useStore((s) => s.setConfig);
  const backends = useStore((s) => s.agentBackends);
  const setBackend = useStore((s) => s.setBackend);
  const setBackends = useStore((s) => s.setBackends);
  const resolved = useStore((s) => s.resolvedBackends);
  const useWeb = useStore((s) => s.useWeb);
  const useObsidian = useStore((s) => s.useObsidian);
  const toggleWeb = useStore((s) => s.toggleWeb);
  const toggleObsidian = useStore((s) => s.toggleObsidian);

  const onProfileChange = async (id: string) => {
    setProfile(id);
    try {
      const fresh = await api.config(id);
      // Refresh recommended map and apply if user hasn't manually overridden;
      // also apply when current selection is empty (auto).
      const merged: Partial<Record<Role, string>> = {};
      (Object.keys(fresh.recommended) as Role[]).forEach((r) => {
        merged[r] = backends[r] || fresh.recommended[r] || "";
      });
      setConfig({ ...fresh });
      setBackends(merged);
    } catch (e) {
      console.error(e);
    }
  };

  const onAuto = async () => {
    const fresh = await api.config(profile);
    setBackends({ ...fresh.recommended });
  };

  const onDefault = async () => {
    const d = await api.defaults();
    setBackends(d);
  };

  if (!config) {
    return (
      <aside className="bg-bg-1 border-l border-subtle p-4 text-ink-3 text-[12px]">
        설정 로딩 중…
      </aside>
    );
  }

  const shortLabel = (k?: string) => {
    if (!k) return "—";
    const last = k.split("/").pop() || k;
    return last.length > 18 ? last.slice(0, 16) + "…" : last;
  };

  return (
    <aside className="bg-bg-1 border-l border-subtle h-full overflow-y-auto p-4 space-y-5">
      {/* LIVE USAGE */}
      <UsageCard />
      {/* COST PROFILE */}
      <section>
        <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium mb-2">
          COST PROFILE
        </div>
        <div className="flex bg-bg-2 border border-subtle rounded-md p-1 gap-1">
          {config.profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => onProfileChange(p.id)}
              className={clsx(
                "flex-1 text-[12px] px-2 py-1.5 rounded transition",
                profile === p.id
                  ? "bg-gradient-to-br from-brand-from to-brand-to text-white shadow-brand"
                  : "text-ink-2 hover:text-ink-1",
              )}
              title={p.label}
            >
              {p.label.split(" ")[0]}
            </button>
          ))}
        </div>
      </section>

      {/* AGENTS */}
      <section>
        <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium mb-2">
          AGENTS
        </div>
        <div className="space-y-1.5">
          {ROLE_META.map((r) => {
            const picked = backends[r.id] || "";
            const actual = resolved[r.id];
            const showActual = !picked && actual;
            return (
              <div key={r.id} className="flex items-center gap-2">
                <div
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: r.color }}
                />
                <span className="text-[13px] text-ink-1 w-12 shrink-0">
                  {r.label}
                </span>
                <select
                  value={picked}
                  onChange={(e) => setBackend(r.id, e.target.value)}
                  className="flex-1 bg-bg-2 border border-subtle rounded text-[11px] text-ink-1 px-1.5 py-1 outline-none truncate"
                  title={picked || (showActual ? `자동: ${actual}` : "")}
                >
                  <option value="">{showActual ? `자동 → ${shortLabel(actual)}` : "(자동)"}</option>
                  {config.backends.slice(0, 80).map((b) => (
                    <option key={b.key} value={b.key}>
                      {shortLabel(b.key)}
                    </option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-2 gap-2 mt-3">
          <button
            onClick={onAuto}
            title={`현재 프로필(${profile})의 추천 모델로 일괄 채우기`}
            className="flex items-center justify-center gap-1.5 bg-bg-2 hover:bg-bg-3 border border-subtle rounded-md py-1.5 text-[12px] text-ink-1"
          >
            <Wand2 size={12} /> 자동
          </button>
          <button
            onClick={onDefault}
            title="무료 모델 기본값으로 일괄 채우기"
            className="flex items-center justify-center gap-1.5 bg-bg-2 hover:bg-bg-3 border border-subtle rounded-md py-1.5 text-[12px] text-ink-1"
          >
            <Sparkles size={12} /> 기본
          </button>
        </div>
      </section>

      {/* OPTIONS */}
      <section>
        <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium mb-2">
          OPTIONS
        </div>
        <div className="space-y-2">
          <Toggle label="🌐 웹검색" checked={useWeb} onChange={toggleWeb} />
          <Toggle label="📓 Obsidian" checked={useObsidian} onChange={toggleObsidian} />
        </div>
      </section>
    </aside>
  );
}

function Toggle({
  label, checked, onChange,
}: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span className="text-[13px] text-ink-1">{label}</span>
      <button
        type="button"
        onClick={onChange}
        className={clsx(
          "w-9 h-5 rounded-full relative transition",
          checked ? "bg-gradient-to-br from-brand-from to-brand-to" : "bg-bg-3",
        )}
      >
        <span
          className={clsx(
            "absolute top-0.5 w-4 h-4 rounded-full bg-white transition",
            checked ? "left-[18px]" : "left-0.5",
          )}
        />
      </button>
    </label>
  );
}

function UsageCard() {
  const usage = useStore((s) => s.usage);
  const status = useStore((s) => s.status);
  const total = usage.prompt + usage.completion;
  const live = status === "running" || status === "starting";
  const fmt = (n: number) => n.toLocaleString();
  const cost = usage.cost_usd;

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium">
          LIVE USAGE
        </div>
        {live && (
          <span className="flex items-center gap-1 text-[10px] text-agent-judge">
            <span className="w-1.5 h-1.5 rounded-full bg-agent-judge animate-pulse" />
            LIVE
          </span>
        )}
      </div>
      <div className="bg-bg-2 border border-subtle rounded-md p-3 space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] text-ink-2">tokens</span>
          <span className="text-[15px] text-ink-0 font-mono tabular-nums">
            {fmt(total)}
          </span>
        </div>
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] text-ink-2">cost (USD)</span>
          <span className="text-[15px] text-ink-0 font-mono tabular-nums">
            ${cost < 0.0001 && cost > 0 ? cost.toExponential(1) : cost.toFixed(4)}
          </span>
        </div>
        <div className="flex justify-between text-[10px] text-ink-2 pt-1 border-t border-subtle">
          <span>↑ in {fmt(usage.prompt)}</span>
          <span>↓ out {fmt(usage.completion)}</span>
        </div>
        {Object.keys(usage.by_role).length > 0 && (
          <div className="pt-2 border-t border-subtle space-y-1">
            {Object.entries(usage.by_role).map(([role, v]) => {
              if (!v) return null;
              const roleColor: Record<string, string> = {
                pro: "#97C459", con: "#E24B4A", judge: "#EF9F27",
                fact: "#378ADD", audience: "#7F77DD",
              };
              return (
                <div key={role} className="flex items-center justify-between text-[10px]">
                  <span className="flex items-center gap-1.5 text-ink-1">
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: roleColor[role] || "#7a776f" }}
                    />
                    {role}
                  </span>
                  <span className="font-mono tabular-nums text-ink-2">
                    {fmt(v.prompt + v.completion)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
