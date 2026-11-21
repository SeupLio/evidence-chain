import { useEffect, useMemo, useState } from "react";

/**
 * 多智能体协作图：不是装饰，而是把「六个角色 + 两条并行支线 + 合流审核」
 * 画成一张能读懂的调度图。传入 stages 时按真实运行状态着色。
 */

export type Agent = {
  id: string;
  name: string;
  code: string;
  stage: string;
  nodes: string[];
  verb: string;
  color: string;
};

const POS: Record<string, { x: number; y: number; r: number }> = {
  plan: { x: 78, y: 150, r: 24 },
  collect: { x: 238, y: 150, r: 26 },
  finance: { x: 452, y: 76, r: 23 },
  industry: { x: 452, y: 224, r: 23 },
  risk: { x: 674, y: 150, r: 24 },
  audit: { x: 848, y: 150, r: 26 },
};

const EDGES: [string, string][] = [
  ["plan", "collect"],
  ["collect", "finance"],
  ["collect", "industry"],
  ["finance", "risk"],
  ["industry", "risk"],
  ["risk", "audit"],
];

function stateOf(agent: Agent, stages?: Record<string, string>) {
  if (!stages) return "idle";
  const st = agent.nodes.map((n) => stages[n]).filter(Boolean);
  if (!st.length) return "pending";
  if (st.includes("fail")) return "fail";
  if (st.includes("start")) return "active";
  if (st.filter((s) => s === "ok" || s === "skip").length === agent.nodes.length) return "done";
  if (st.includes("ok")) return "active";
  return "pending";
}

const STATE_LABEL: Record<string, string> = {
  idle: "待运行", pending: "排队", active: "进行中", done: "已完成", fail: "失败",
};

export default function AgentFlow({
  agents,
  stages,
  height = 300,
  onPick,
  picked,
}: {
  agents: Agent[];
  stages?: Record<string, string>;
  height?: number;
  onPick?: (id: string) => void;
  picked?: string | null;
}) {
  const [auto, setAuto] = useState(0);

  useEffect(() => {
    if (stages && Object.keys(stages).length) return;
    const t = setInterval(() => setAuto((a) => (a + 1) % agents.length), 2600);
    return () => clearInterval(t);
  }, [agents.length, stages]);

  const list = useMemo(() => {
    const byId = Object.fromEntries(agents.map((a) => [a.id, a]));
    return ["plan", "collect", "finance", "industry", "risk", "audit"]
      .map((id) => byId[id]).filter(Boolean) as Agent[];
  }, [agents]);

  const activeId = picked || (stages && Object.keys(stages).length ? null : list[auto]?.id);
  const flowState = (from: string, to: string) => {
    if (!stages) return "idle";
    const a = stateOf(list.find((x) => x.id === from)!, stages);
    const b = stateOf(list.find((x) => x.id === to)!, stages);
    if (a === "fail" || b === "fail") return "fail";
    if (a === "done" && (b === "active" || b === "done")) return "on";
    if (a === "done") return "ready";
    return "idle";
  };

  return (
    <div className="af-wrap" style={{ height }}>
      <svg viewBox="0 0 930 300" className="af-svg" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="af-line" x1="0" x2="1">
            <stop offset="0%" stopColor="rgba(214,251,106,.55)" />
            <stop offset="100%" stopColor="rgba(232,197,131,.55)" />
          </linearGradient>
          <filter id="af-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <text x="20" y="22" className="af-axis">计划</text>
        <text x="392" y="22" className="af-axis">并行支线</text>
        <text x="620" y="22" className="af-axis">解释</text>
        <text x="800" y="22" className="af-axis">发布</text>

        {EDGES.map(([a, b], i) => {
          const p = POS[a], q = POS[b];
          const mx = (p.x + q.x) / 2;
          const st = flowState(a, b);
          return (
            <g key={i}>
              <path
                d={`M${p.x + p.r},${p.y} C ${mx},${p.y} ${mx},${q.y} ${q.x - q.r},${q.y}`}
                className={"af-edge " + st}
              />
              {st === "on" && (
                <circle r="2.6" className="af-pulse">
                  <animateMotion
                    dur="1.8s"
                    repeatCount="indefinite"
                    path={`M${p.x + p.r},${p.y} C ${mx},${p.y} ${mx},${q.y} ${q.x - q.r},${q.y}`}
                  />
                </circle>
              )}
            </g>
          );
        })}

        {list.map((a) => {
          const p = POS[a.id];
          if (!p) return null;
          const st = stateOf(a, stages);
          const isActive = activeId === a.id;
          return (
            <g
              key={a.id}
              className={"af-node " + st + (isActive ? " focus" : "")}
              transform={`translate(${p.x},${p.y})`}
              onMouseEnter={() => onPick?.(a.id)}
              onClick={() => onPick?.(a.id)}
              style={{ cursor: onPick ? "pointer" : "default" }}
            >
              <circle r={p.r + 9} className="af-halo" />
              <circle r={p.r} className="af-core" stroke={a.color} />
              {st === "active" && <circle r={p.r + 4} className="af-ring" stroke={a.color} />}
              <text y={4} textAnchor="middle" className="af-code">{a.code}</text>
              <text y={p.r + 17} textAnchor="middle" className="af-name">{a.stage}</text>
              <text y={p.r + 29} textAnchor="middle" className="af-state">
                {STATE_LABEL[st] || st}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
