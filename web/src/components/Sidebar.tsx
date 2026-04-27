"use client";
import { Search, Pin, Calendar, Folder, Wand2, Settings, Activity, GitMerge } from "lucide-react";
import { useStore } from "@/lib/store";
import { useState } from "react";
import Link from "next/link";
import type { ArchiveItem } from "@/lib/api";

interface ThreadCluster {
  thread_id: number;
  items: ArchiveItem[]; // 최신순 (topic 노출은 가장 최근 것)
}

function clusterByThread(items: ArchiveItem[]): ThreadCluster[] {
  // 입력 items는 id DESC 정렬. thread별 묶고, 클러스터 자체는 가장 최신 id 기준 정렬 유지.
  const map = new Map<number, ArchiveItem[]>();
  const order: number[] = [];
  for (const it of items) {
    const tid = it.thread_id ?? it.id;
    if (!map.has(tid)) {
      map.set(tid, []);
      order.push(tid);
    }
    map.get(tid)!.push(it);
  }
  return order.map((tid) => ({ thread_id: tid, items: map.get(tid)! }));
}

export function Sidebar() {
  const archive = useStore((s) => s.archive);
  const loadDebate = useStore((s) => s.loadDebate);
  const lastDebateId = useStore((s) => s.lastDebateId);
  const [q, setQ] = useState("");
  const [openThreads, setOpenThreads] = useState<Record<number, boolean>>({});
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  const groups = archive.map((g) => {
    const filtered = g.items.filter((i) =>
      !q ? true : i.topic.toLowerCase().includes(q.toLowerCase()),
    );
    return { ...g, clusters: clusterByThread(filtered) };
  });

  const groupIcon = (label: string) =>
    label === "오늘" ? <Pin size={14} /> : label === "어제" ? <Calendar size={14} /> : <Folder size={14} />;

  return (
    <aside className="flex flex-col h-full p-4 gap-4 bg-bg-1 border-r border-subtle">
      <div className="text-[11px] uppercase tracking-wider text-ink-2 font-medium px-1">
        ARCHIVE
      </div>

      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="검색…"
          className="w-full bg-bg-2 border border-subtle rounded-md pl-8 pr-3 h-8 text-[13px] text-ink-1 outline-none focus:border-brand-from focus:ring-2 focus:ring-brand-from/30"
        />
      </div>

      <div className="flex flex-col gap-1 overflow-y-auto -mx-2 px-2 flex-1" style={{ minHeight: 0 }}>
        {groups.map((g) => (
          <div key={g.label} className="mb-2">
            <button
              onClick={() => setCollapsedGroups((p) => ({ ...p, [g.label]: !p[g.label] }))}
              className="flex items-center gap-2 w-full px-2 py-2 rounded-md hover:bg-bg-2 text-[13px] text-ink-0"
            >
              {groupIcon(g.label)}
              <span className="flex-1 text-left">{g.label}</span>
              <span className="text-ink-2 text-[11px]">({g.clusters.length})</span>
            </button>
            {!collapsedGroups[g.label] && <ul className="ml-1 border-l border-subtle pl-2 mt-1 space-y-1">
              {g.clusters.map((cl) => {
                const head = cl.items[0]; // 클러스터 내 가장 최근 토론
                const hasThread = cl.items.length > 1;
                const isOpen = !!openThreads[cl.thread_id];
                const activeCls = (id: number) =>
                  lastDebateId === id ? "text-ink-0 font-medium" : "text-ink-1";
                return (
                  <li key={cl.thread_id} className="text-[12px]">
                    <div
                      className={`flex items-center gap-1.5 hover:text-ink-0 truncate cursor-pointer py-1 ${activeCls(head.id)}`}
                      title={`${head.topic}${hasThread ? ` · ${cl.items.length}개 라운드` : ""}`}
                    >
                      {hasThread ? (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setOpenThreads((p) => ({ ...p, [cl.thread_id]: !isOpen }));
                          }}
                          className="text-emerald-400 hover:text-emerald-300 shrink-0"
                          aria-label="thread toggle"
                        >
                          <GitMerge size={11} />
                        </button>
                      ) : (
                        <span className="text-ink-3 shrink-0">·</span>
                      )}
                      <span
                        onClick={() => loadDebate(head.id)}
                        className="flex-1 truncate"
                      >
                        {head.topic}
                      </span>
                      {hasThread && (
                        <span className="text-emerald-400/80 text-[10px] shrink-0">
                          ×{cl.items.length}
                        </span>
                      )}
                    </div>
                    {hasThread && isOpen && (
                      <ul className="ml-4 mt-1 space-y-0.5 border-l border-emerald-900/40 pl-2">
                        {cl.items.map((it, idx) => (
                          <li
                            key={it.id}
                            onClick={() => loadDebate(it.id)}
                            className={`text-[11px] hover:text-ink-0 truncate cursor-pointer py-0.5 ${activeCls(it.id)}`}
                            title={`${it.topic} (${it.created.slice(0, 16).replace("T", " ")})`}
                          >
                            <span className="text-emerald-500/70">R{cl.items.length - idx}</span>{" "}
                            {it.created.slice(11, 16)} · {it.summary?.slice(0, 30) || it.topic.slice(0, 30)}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>}
          </div>
        ))}
      </div>

      <div className="border-t border-subtle pt-3 space-y-1">
        <Link
          href="/refinery"
          className="flex items-center gap-2 w-full px-2 py-2 rounded-md hover:bg-bg-2 text-[13px] text-ink-2"
        >
          <Wand2 size={14} /> AI 정제소
        </Link>
        <Link
          href="/status"
          className="flex items-center gap-2 w-full px-2 py-2 rounded-md hover:bg-bg-2 text-[13px] text-ink-2"
        >
          <Activity size={14} /> 관제실
        </Link>
        <button className="flex items-center gap-2 w-full px-2 py-2 rounded-md hover:bg-bg-2 text-[13px] text-ink-2">
          <Settings size={14} /> 설정
        </button>
      </div>
    </aside>
  );
}
