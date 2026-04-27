"use client";
import { motion } from "framer-motion";
import { useStore } from "@/lib/store";
import clsx from "clsx";

const ROLES = [
  { id: "pro", label: "찬성", color: "#97C459", x: 35, y: 50 },
  { id: "con", label: "반대", color: "#E24B4A", x: 65, y: 50 },
  { id: "judge", label: "심판", color: "#EF9F27", x: 50, y: 30 },
  { id: "fact", label: "팩트", color: "#378ADD", x: 42, y: 72 },
  { id: "audience", label: "청중", color: "#7F77DD", x: 58, y: 72 },
] as const;

type RoleDef = (typeof ROLES)[number];

function NodeLabel({ role, model }: { role: RoleDef; model?: string }) {
  return (
    <text
      x={role.x}
      y={role.y + 11}
      textAnchor="middle"
      className="fill-ink-3"
      style={{ fontSize: 2.2 }}
    >
      {model || ""}
    </text>
  );
}

export function AgentGraph() {
  const active = useStore((s) => s.activeRole);
  const status = useStore((s) => s.status);
  const backends = useStore((s) => s.agentBackends);
  const resolved = useStore((s) => s.resolvedBackends);

  const modelLabel = (k?: string) => {
    if (!k) return "";
    const last = k.split("/").pop() || k;
    return last.length > 14 ? last.slice(0, 12) + "…" : last;
  };

  const labelFor = (id: string) =>
    modelLabel(
      backends[id as keyof typeof backends] ||
        resolved[id as keyof typeof resolved] ||
        "",
    );

  return (
    <svg viewBox="0 0 100 100" className="w-full h-full max-h-[420px]" preserveAspectRatio="xMidYMid meet">
      {/* connection lines */}
      <g stroke="rgba(255,255,255,0.07)" strokeWidth={0.2} strokeDasharray="0.8 0.8">
        <line x1={ROLES[0].x} y1={ROLES[0].y} x2={ROLES[1].x} y2={ROLES[1].y} />
        <line x1={ROLES[2].x} y1={ROLES[2].y} x2={ROLES[0].x} y2={ROLES[0].y} />
        <line x1={ROLES[2].x} y1={ROLES[2].y} x2={ROLES[1].x} y2={ROLES[1].y} />
        <line x1={ROLES[3].x} y1={ROLES[3].y} x2={ROLES[0].x} y2={ROLES[0].y} />
        <line x1={ROLES[4].x} y1={ROLES[4].y} x2={ROLES[1].x} y2={ROLES[1].y} />
      </g>

      {/* orbital ring */}
      <ellipse
        cx={50} cy={55} rx={28} ry={18}
        fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={0.15} strokeDasharray="0.5 0.5"
      />

      {ROLES.map((r) => {
        const isActive = active === r.id;
        const isBig = r.id === "judge" || r.id === "pro" || r.id === "con";
        const radius = isBig ? 5.2 : 3.6;
        return (
          <g key={r.id}>
            {isActive && (
              <motion.circle
                cx={r.x} cy={r.y} r={radius}
                fill={r.color}
                initial={{ opacity: 0.5, scale: 1 }}
                animate={{ opacity: 0, scale: 1.8 }}
                transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }}
                style={{ transformOrigin: `${r.x}px ${r.y}px` }}
              />
            )}
            <motion.circle
              cx={r.x} cy={r.y} r={radius}
              fill={r.color}
              stroke={isActive ? "#fff" : "rgba(255,255,255,0.15)"}
              strokeWidth={isActive ? 0.5 : 0.2}
              animate={{ scale: isActive ? 1.08 : 1 }}
              style={{ transformOrigin: `${r.x}px ${r.y}px` }}
            />
            <text
              x={r.x} y={r.y + 0.8}
              textAnchor="middle"
              className={clsx("fill-white font-semibold")}
              style={{ fontSize: isBig ? 2.4 : 1.8 }}
            >
              {r.label}
            </text>
            <NodeLabel role={r} model={labelFor(r.id)} />
          </g>
        );
      })}

      {status === "running" && (
        <text x={50} y={95} textAnchor="middle" className="fill-ink-3" style={{ fontSize: 2.4 }}>
          진행 중…
        </text>
      )}
    </svg>
  );
}
