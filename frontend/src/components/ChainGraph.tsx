import { useMemo, useState } from "react";

/**
 * 产业链图：分层布局而不是力导向。
 * 供应链本身有方向（上游 → 中游 → 渠道 → 需求），分层比「弹簧」更能读出结构。
 * 悬停高亮邻接，点击看节点说明与财务数据。
 */

type Node = {
  node_id: string;
  name: string;
  role: string;
  note?: string;
  ticker?: string | null;
  entity_id?: string | null;
  degree?: number;
};
type Edge = { src: string; dst: string; relation: string; basis?: string };

const COLUMNS = [
  { role: "upstream", label: "上游原料 / 部件", x: 80 },
  { role: "packaging", label: "包材 / 辅材", x: 260 },
  { role: "core", label: "中游制造（样本公司）", x: 480 },
  { role: "downstream", label: "渠道 / 服务", x: 700 },
  { role: "demand", label: "终端需求", x: 890 },
];

const ROLE_COLOR: Record<string, string> = {
  upstream: "#8fa3c8",
  packaging: "#7f8ea8",
  core: "#d6fb6a",
  downstream: "#e8c583",
  demand: "#c8102e",
};

export default function ChainGraph({
  nodes,
  edges,
  metrics,
  subjectId,
  height = 420,
}: {
  nodes: Node[];
  edges: Edge[];
  metrics?: Record<string, any>;
  subjectId?: string;
  height?: number;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  const layout = useMemo(() => {
    const W = 980;
    const byRole: Record<string, Node[]> = {};
    for (const n of nodes) {
      const role = COLUMNS.some((c) => c.role === n.role) ? n.role : "core";
      (byRole[role] = byRole[role] || []).push(n);
    }
    const maxCount = Math.max(...COLUMNS.map((c) => (byRole[c.role] || []).length), 1);
    const H = Math.max(height, maxCount * 34 + 34);
    const pos: Record<string, { x: number; y: number; r: number; n: Node }> = {};
    for (const col of COLUMNS) {
      const list = (byRole[col.role] || []).sort((a, b) => (b.degree || 0) - (a.degree || 0));
      const gap = H / (list.length + 1);
      list.forEach((n, i) => {
        pos[n.node_id] = {
          x: col.x,
          y: gap * (i + 1),
          r: col.role === "core" ? 17 : Math.max(7, Math.min(13, 5 + (n.degree || 0) * 1.1)),
          n,
        };
      });
    }
    return { pos, W, H };
  }, [nodes, height]);

  const neighbors = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    for (const e of edges) {
      (m[e.src] = m[e.src] || new Set()).add(e.dst);
      (m[e.dst] = m[e.dst] || new Set()).add(e.src);
    }
    return m;
  }, [edges]);

  const focus = hover || picked;
  const active = useMemo(() => {
    if (!focus) return null;
    return new Set([focus, ...(neighbors[focus] || [])]);
  }, [focus, neighbors]);

  const { pos, W, H } = layout;
  const pickedNode = picked ? nodes.find((n) => n.node_id === picked) : null;
  const pickedMetric = pickedNode?.entity_id ? metrics?.[pickedNode.entity_id] : null;
  const nameOf = useMemo(() => Object.fromEntries(nodes.map((n) => [n.node_id, n.name])), [nodes]);
  const pickedEdges = picked
    ? edges.filter((e) => e.src === picked || e.dst === picked).slice(0, 4)
    : [];

  return (
    <div className="chain-wrap">
      <svg className="chain-svg" viewBox={`0 0 ${W} ${H}`} style={{ height: H }}>
        {COLUMNS.map((c) => (
          <text key={c.role} x={c.x} y={14} textAnchor="middle"
            style={{ fontSize: 8.5, fill: "var(--dim)", letterSpacing: ".08em" }}>
            {c.label}
          </text>
        ))}

        {edges.map((e, i) => {
          const a = pos[e.src];
          const b = pos[e.dst];
          if (!a || !b) return null;
          const hot = focus && (e.src === focus || e.dst === focus);
          const dim = active && !hot;
          const mx = (a.x + b.x) / 2;
          return (
            <path
              key={i}
              className={"ce" + (hot ? " hot" : "")}
              d={`M${a.x + a.r},${a.y} C ${mx},${a.y} ${mx},${b.y} ${b.x - b.r},${b.y}`}
              style={{ opacity: dim ? 0.06 : hot ? 0.9 : 0.3, strokeWidth: hot ? 1.4 : 0.9 }}
            />
          );
        })}

        {nodes.map((n) => {
          const p = pos[n.node_id];
          if (!p) return null;
          const isSubject = n.entity_id && n.entity_id === subjectId;
          const dim = active && !active.has(n.node_id);
          const color = ROLE_COLOR[n.role] || "#8fa3c8";
          const isCore = n.role === "core";
          return (
            <g
              key={n.node_id}
              className={"cn" + (isCore ? " core" : "") + (dim ? " dim" : "")}
              transform={`translate(${p.x},${p.y})`}
              onMouseEnter={() => setHover(n.node_id)}
              onMouseLeave={() => setHover(null)}
              onClick={() => setPicked(picked === n.node_id ? null : n.node_id)}
            >
              <circle
                r={p.r}
                style={{ fill: isCore ? "var(--chain-core-fill)" : "var(--chain-node-fill)" }}
                stroke={isSubject ? "#c8102e" : color}
                strokeWidth={isSubject ? 2 : 1.2}
              />
              {isCore && <circle r={4} style={{ fill: color }} />}
              <text
                y={p.r + 11}
                textAnchor="middle"
                style={{ fontSize: isCore ? 10 : 9 }}
              >
                {n.name.length > 8 ? n.name.slice(0, 8) : n.name}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="chain-legend">
        {COLUMNS.map((c) => (
          <span key={c.role}><i style={{ background: ROLE_COLOR[c.role] }} />{c.label}</span>
        ))}
        <span style={{ marginLeft: "auto" }}>共 {nodes.length} 个节点 / {edges.length} 条关系 · 点节点看说明</span>
      </div>

      {pickedNode && (
        <div className="chain-tip on" style={{ left: 12, bottom: 34, maxWidth: 360 }}>
          <b>{pickedNode.name}</b>
          {pickedNode.ticker && <span className="mono" style={{ color: "var(--dim)", marginLeft: 6, fontSize: 10 }}>{pickedNode.ticker}</span>}
          {pickedNode.note && <div className="r">{pickedNode.note}</div>}
          <div className="r">
            关联 {neighbors[pickedNode.node_id]?.size || 0} 个节点
            {pickedMetric?.revenue ? ` · 2025 营收 ${(pickedMetric.revenue / 1e8).toFixed(0)} 亿元` : ""}
            {pickedMetric?.gross_margin != null ? ` · 毛利率 ${pickedMetric.gross_margin}%` : ""}
          </div>
          {pickedEdges.map((e, i) => (
            <div className="r ce-line" key={i}>
              <span className="ce-rel">{e.relation}</span>
              {nameOf[e.src]} → {nameOf[e.dst]}
              {e.basis ? <em>依据：{e.basis}</em> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
