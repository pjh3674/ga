"use client";
import { motion, AnimatePresence } from "framer-motion";
import { useStore } from "@/lib/store";
import { useEffect, useRef, useState } from "react";

const ROLE_COLOR: Record<string, string> = {
  pro: "#97C459",
  con: "#E24B4A",
  judge: "#EF9F27",
  fact: "#378ADD",
  audience: "#7F77DD",
};
const ROLE_LABEL: Record<string, string> = {
  pro: "찬성", con: "반대", judge: "심판", fact: "팩트", audience: "청중",
};

function Typewriter({ text, speed = 12 }: { text: string; speed?: number }) {
  const [shown, setShown] = useState(0);
  const ref = useRef(text);
  useEffect(() => {
    ref.current = text;
    setShown(0);
    if (!text) return;
    let i = 0;
    // Adaptive: longer text → bigger chunk so total time stays bounded (~3s)
    const chunk = Math.max(1, Math.ceil(text.length / 220));
    const id = setInterval(() => {
      i += chunk;
      if (i >= text.length) {
        setShown(text.length);
        clearInterval(id);
      } else {
        setShown(i);
      }
    }, speed);
    return () => clearInterval(id);
  }, [text, speed]);
  return (
    <>
      {text.slice(0, shown)}
      {shown < text.length && (
        <span className="inline-block w-[6px] h-[14px] -mb-0.5 bg-ink-1 ml-0.5 animate-pulse" />
      )}
    </>
  );
}

export function MessageList() {
  const messages = useStore((s) => s.messages);
  const status = useStore((s) => s.status);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  if (!messages.length) return null;

  const lastIdx = messages.length - 1;
  const isLive = status === "running" || status === "starting";

  return (
    <div className="px-4 py-2 space-y-3">
      <AnimatePresence initial={false}>
        {messages.map((m, idx) => {
          const color = ROLE_COLOR[m.role] || "#7a776f";
          const label = ROLE_LABEL[m.role] || m.role;
          const animate = isLive && idx === lastIdx && m.role !== "user" && m.role !== "system";
          return (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className="bg-bg-1 border border-subtle rounded-lg p-3"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="text-[11px] px-2 py-0.5 rounded-md font-medium"
                  style={{ background: color + "22", color }}
                >
                  {label}
                </span>
                {m.round != null && (
                  <span className="text-[11px] text-ink-2">R{m.round}</span>
                )}
                {m.model && (
                  <span className="text-[11px] text-ink-2 ml-auto truncate max-w-[200px]">
                    {m.model}
                  </span>
                )}
              </div>
              <div className="text-[13px] text-ink-1 whitespace-pre-wrap leading-relaxed">
                {animate ? <Typewriter text={m.content} /> : m.content}
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  );
}
