"use client";
import { create } from "zustand";
import { ArchiveGroup, ConfigBundle, DebateMessage, Role } from "./api";

export type ArenaStatus = "idle" | "starting" | "running" | "saving" | "done" | "error";

interface State {
  config: ConfigBundle | null;
  archive: ArchiveGroup[];
  topic: string;
  context: string;
  rounds: number;
  profile: string;
  mode: string;
  useWeb: boolean;
  useObsidian: boolean;
  agentBackends: Partial<Record<Role, string>>;
  status: ArenaStatus;
  currentRound: number;
  activeRole: string | null;
  messages: DebateMessage[];
  verdict: string;
  errorMsg: string | null;
  warning: string | null;
  resolvedBackends: Partial<Record<Role, string>>;  // per-role models actually picked
  lastDebateId: number | null;  // DB id of most recent completed debate (for resume)
  usage: {
    prompt: number;
    completion: number;
    cost_usd: number;
    by_role: Partial<Record<Role, { prompt: number; completion: number; cost_usd: number }>>;
  };
  setConfig: (c: ConfigBundle) => void;
  setArchive: (a: ArchiveGroup[]) => void;
  setTopic: (t: string) => void;
  setContext: (c: string) => void;
  setRounds: (n: number) => void;
  setProfile: (p: string) => void;
  setMode: (m: string) => void;
  toggleWeb: () => void;
  toggleObsidian: () => void;
  setBackend: (role: Role, key: string) => void;
  setBackends: (b: Partial<Record<Role, string>>) => void;
  resetForRun: () => void;
  setStatus: (s: ArenaStatus) => void;
  setActiveRole: (r: string | null) => void;
  setRound: (n: number) => void;
  pushMessage: (m: DebateMessage) => void;
  setVerdict: (v: string) => void;
  setError: (e: string | null) => void;
  setWarning: (w: string | null) => void;
  setResolvedBackends: (b: Partial<Record<Role, string>>) => void;
  setUsage: (u: State["usage"]) => void;
  resetUsage: () => void;
  setLastDebateId: (id: number | null) => void;
  resetForResume: () => void;
  loadDebate: (id: number) => Promise<void>;
}

export const useStore = create<State>((set) => ({
  config: null,
  archive: [],
  topic: "",
  context: "",
  rounds: 3,
  profile: "balanced",
  mode: "debate",
  useWeb: true,
  useObsidian: true,
  agentBackends: {},
  status: "idle",
  currentRound: 0,
  activeRole: null,
  messages: [],
  verdict: "",
  errorMsg: null,
  warning: null,
  resolvedBackends: {},
  lastDebateId: null,
  usage: { prompt: 0, completion: 0, cost_usd: 0, by_role: {} },
  setConfig: (c) =>
    set((s) => {
      // Prefer "balanced" if available — economy free-tier often returns empty debates.
      const preferred = c.profiles.find((p) => p.id === "balanced")?.id
        || c.profiles[0]?.id
        || "balanced";
      return {
        config: c,
        profile: s.profile || preferred,
        mode: s.mode || c.modes[0]?.id || "debate",
        agentBackends: { ...c.recommended, ...s.agentBackends },
      };
    }),
  setArchive: (a) => set({ archive: a }),
  setTopic: (t) => set({ topic: t }),
  setContext: (c) => set({ context: c }),
  setRounds: (n) => set({ rounds: n }),
  setProfile: (p) => set({ profile: p }),
  setMode: (m) => set({ mode: m }),
  toggleWeb: () => set((s) => ({ useWeb: !s.useWeb })),
  toggleObsidian: () => set((s) => ({ useObsidian: !s.useObsidian })),
  setBackend: (role, key) =>
    set((s) => ({ agentBackends: { ...s.agentBackends, [role]: key } })),
  setBackends: (b) => set({ agentBackends: b }),
  resetForRun: () =>
    set({
      messages: [],
      verdict: "",
      currentRound: 0,
      activeRole: null,
      errorMsg: null,
      warning: null,
      resolvedBackends: {},
      usage: { prompt: 0, completion: 0, cost_usd: 0, by_role: {} },
      status: "starting",
    }),
  setStatus: (status) => set({ status }),
  setActiveRole: (activeRole) => set({ activeRole }),
  setRound: (currentRound) => set({ currentRound }),
  pushMessage: (m) => set((s) => ({ messages: [...s.messages, m], activeRole: m.role })),
  setVerdict: (verdict) => set({ verdict }),
  setError: (errorMsg) => set({ errorMsg, status: errorMsg ? "error" : "idle" }),
  setWarning: (warning) => set({ warning }),
  setResolvedBackends: (resolvedBackends) => set({ resolvedBackends }),
  setUsage: (usage) => set({ usage }),
  resetUsage: () => set({ usage: { prompt: 0, completion: 0, cost_usd: 0, by_role: {} } }),
  setLastDebateId: (lastDebateId) => set({ lastDebateId }),
  resetForResume: () =>
    set({
      verdict: "",
      currentRound: 0,
      activeRole: null,
      errorMsg: null,
      warning: null,
      status: "starting",
    }),
  loadDebate: async (id: number) => {
    try {
      const d: any = await (await fetch(`/api/debates/${id}`)).json();
      const msgs = (d.messages || []).map((m: any, i: number) => ({
        id: `hist-${id}-${i}`,
        role: m.role || "system",
        speaker: m.name || m.role || "?",
        content: m.content || "",
        round: m.round,
        model: m.model,
      }));
      set({
        topic: d.topic || "",
        messages: msgs,
        verdict: d.verdict || "",
        currentRound: 0,
        activeRole: null,
        errorMsg: null,
        warning: null,
        status: "done",
        lastDebateId: id,
      });
    } catch (e) {
      set({ errorMsg: `이력 로드 실패: ${(e as any)?.message || e}`, status: "error" });
    }
  },
}));
