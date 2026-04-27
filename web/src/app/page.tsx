"use client";
import { useEffect } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Arena } from "@/components/Arena";
import { RightPanel } from "@/components/RightPanel";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";

export default function Page() {
  const setConfig = useStore((s) => s.setConfig);
  const setArchive = useStore((s) => s.setArchive);
  const refreshAt = useStore((s) => s.status);

  useEffect(() => {
    api.config().then(setConfig).catch(console.error);
    api.list().then(setArchive).catch(console.error);
  }, [setConfig, setArchive]);

  // refresh archive when a debate finishes
  useEffect(() => {
    if (refreshAt === "done") {
      api.list().then(setArchive).catch(console.error);
    }
  }, [refreshAt, setArchive]);

  return (
    <div className="h-screen w-screen grid grid-cols-[260px_1fr_300px] overflow-hidden">
      <Sidebar />
      <Arena />
      <RightPanel />
    </div>
  );
}
