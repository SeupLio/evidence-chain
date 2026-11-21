import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ArrowUpRight, File, Layers, Shield } from "../components/icons";

const TYPE_COLOR: Record<string, string> = {
  section: "#d6fb6a",
  claim: "#f3f4f6",
  metric: "#e8c583",
  fact: "#9be6c4",
  rule: "#ff7a6b",
  bench: "#b79cff",
  edge: "#7fa6ff",
  document: "#c8102e",
};

const TYPE_LABEL: Record<string, string> = {
  section: "章节", claim: "结论", metric: "指标", fact: "事实",
  rule: "规则", bench: "同业基准", edge: "关系边", document: "原件",
};

const X: Record<string, number> = {
  section: 78, claim: 300, metric: 600, rule: 600, bench: 600, edge: 600,
  fact: 828, document: 1002,
};

const NODE_W: Record<string, number> = {
  section: 128, claim: 168, metric: 158, rule: 128, bench: 118, edge: 118,
  fact: 150, document: 148,
};

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export default function ProvenanceView({
  reportId,
  versionNo,
  onRef,
}: {
  reportId: string | null;
  versionNo: number | null;
  onRef: (ref: string) => void;
}) {
  const [data, setData] = useState<any>(null);
  const [section, setSection] = useState<string>("overview");
  const [picked, setPicked] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [ev, setEv] = useState<any>(null);

  useEffect(() => {
    if (!reportId || !versionNo) return;
    setData(null);
    api.provenance(reportId, versionNo).then(setData).catch(() => setData(null));
  }, [reportId, versionNo]);

  useEffect(() => {
    const node = data?.nodes?.find((n: any) => n.id === picked);
    setEv(null);
    if (node?.ref) api.evidence(node.ref).then(setEv).catch(() => setEv(null));
  }, [picked, data]);

  const view = useMemo(() => {
    if (!data) return null;
    const all = data.nodes as any[];
    const edges = data.edges as any[];
    const useAll = section === "all" || !(data.sections || []).some((s: any) => s.section === section);
    let keep = new Set(all.map((n) => n.id));
    if (!useAll) {
      const sid = `sec:${section}`;
      const adj: Record<string, string[]> = {};
      for (const e of edges) (adj[e.source] = adj[e.source] || []).push(e.target);
      keep = new Set([sid]);
      const stack = [sid];
      while (stack.length) {
        const cur = stack.pop()!;
        for (const nxt of adj[cur] || []) {
          if (!keep.has(nxt)) { keep.add(nxt); stack.push(nxt); }
        }
      }
    }
    const nodes = all.filter((n) => keep.has(n.id));
    const shownEdges = edges.filter((e) => keep.has(e.source) && keep.has(e.target));
    const byLayer: Record<number, any[]> = {};
    const order = Object.keys(X);
    for (const n of nodes) {
      const li = order.indexOf(n.type);
      (byLayer[li] = byLayer[li] || []).push(n);
    }
    for (const k of Object.keys(byLayer)) {
      byLayer[+k].sort((a, b) => {
        const sa = (a.section || "").localeCompare(b.section || "");
        return sa || String(a.label).localeCompare(String(b.label));
      });
    }
    const maxN = Math.max(...Object.values(byLayer).map((v) => v.length), 1);
    const H = Math.max(560, maxN * 34 + 80);
    const pos: Record<string, { x: number; y: number; w: number }> = {};
    for (const [li, list] of Object.entries(byLayer)) {
      const x = X[order[+li]];
      const gap = (H - 60) / (list.length + 1);
      list.forEach((n, i) => {
        pos[n.id] = { x, y: 40 + gap * (i + 1), w: NODE_W[n.type] || 130 };
      });
    }
    return { nodes, edges: shownEdges, pos, H, W: 1120 };
  }, [data, section]);

  const neighbors = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    for (const e of view?.edges || []) {
      (m[e.source] = m[e.source] || new Set()).add(e.target);
      (m[e.target] = m[e.target] || new Set()).add(e.source);
    }
    return m;
  }, [view]);

  const focus = hover || picked;
  const active = useMemo(() => {
    if (!focus) return null;
    return new Set([focus, ...(neighbors[focus] || [])]);
  }, [focus, neighbors]);

  if (!reportId) return <div className="empty">还没有报告，先在研究台运行一次。</div>;
  if (!data) return <div className="empty">证据地图生成中…</div>;

  const pickedNode = data.nodes.find((n: any) => n.id === picked);
  const stats = data.stats;
  const sections = data.sections || [];

  return (
    <div className="view-enter pv">
      <div className="page-head pv-head">
        <div>
          <div className="kicker">Provenance graph</div>
          <h2>证据地图</h2>
          <p className="sub">
            从章节到结论，再到指标、事实与原件。所有边都来自这一版报告实际使用的引用，
            不是模型画出来的关系图。
          </p>
        </div>
        <div className="spacer" />
        <span className="badge-mode">版本 <b>v{data.version_no}</b></span>
        <span className="badge-mode">可追溯 <b>{stats.edges}</b> 条边</span>
      </div>

      <div className="pv-stats">
        {[
          ["章节", stats.sections, Layers],
          ["结论", stats.claims, Shield],
          ["指标", stats.metrics, ArrowUpRight],
          ["事实", stats.facts, File],
          ["原件", stats.documents, File],
        ].map(([label, value, Icon]: any) => (
          <div className="pv-stat" key={label}>
            <Icon size={13} />
            <b>{value}</b>
            <span>{label}</span>
          </div>
        ))}
        <div className="pv-legend">
          {Object.entries(TYPE_LABEL).map(([k, v]) => (
            <span key={k}><i style={{ background: TYPE_COLOR[k] }} />{v}</span>
          ))}
        </div>
      </div>

      <div className="pv-body">
        <aside className="pv-side">
          <div className="pv-side-h">章节</div>
          <button className={"pv-sec" + (section === "all" ? " on" : "")} onClick={() => { setSection("all"); setPicked(null); }}>
            <span className="n">ALL</span>
            <span className="t">全部章节</span>
            <span className="c">{stats.claims} 条结论</span>
          </button>
          {sections.map((s: any) => (
            <button
              key={s.section}
              className={"pv-sec" + (section === s.section ? " on" : "")}
              onClick={() => { setSection(s.section); setPicked(null); }}
            >
              <span className="n">{String(sections.indexOf(s) + 1).padStart(2, "0")}</span>
              <span className="t">{s.title}</span>
              <span className="c">{s.claims} 结论 · {s.documents} 原件</span>
            </button>
          ))}
          <div className="pv-side-note">
            原件数按「沿引用边可达」计算；没有引用的章节显示 0，而不是猜测。
          </div>
        </aside>

        <div className="pv-canvas">
          <div className="pv-canvas-h">
            <span>{section === "all" ? "全部章节" : sections.find((s: any) => s.section === section)?.title}</span>
            <span className="spacer" />
            <span className="mono">{view?.nodes.length} 节点 · {view?.edges.length} 边</span>
          </div>
          <div className="pv-scroll">
            <svg viewBox={`0 0 ${view!.W} ${view!.H}`} style={{ width: "100%", minWidth: 760 }}>
              {Object.entries(X).map(([k, x], i) => (
                <g key={k}>
                  <line x1={x} y1={22} x2={x} y2={view!.H - 10} className="pv-guide" />
                  <text x={x} y={14} textAnchor="middle" className="pv-layer">{TYPE_LABEL[k]}</text>
                  {i === 0 && null}
                </g>
              ))}
              {view!.edges.map((e, i) => {
                const a = view!.pos[e.source], b = view!.pos[e.target];
                if (!a || !b) return null;
                const hot = focus === e.source || focus === e.target;
                const dim = active && !hot;
                const mx = (a.x + b.x) / 2;
                return (
                  <path
                    key={i}
                    d={`M${a.x + a.w / 2},${a.y} C ${mx},${a.y} ${mx},${b.y} ${b.x - b.w / 2},${b.y}`}
                    className={"pv-edge " + e.kind + (hot ? " hot" : "")}
                    style={{ opacity: dim ? 0.05 : hot ? 0.92 : undefined }}
                  />
                );
              })}
              {view!.nodes.map((n: any) => {
                const p = view!.pos[n.id];
                if (!p) return null;
                const dim = active && !active.has(n.id);
                const color = TYPE_COLOR[n.type];
                const isPicked = picked === n.id;
                const label = truncate(String(n.label || ""), n.type === "claim" ? 22 : 18);
                const h = n.type === "document" ? 32 : 27;
                return (
                  <g
                    key={n.id}
                    className={"pv-node " + n.type + (dim ? " dim" : "") + (isPicked ? " picked" : "")}
                    transform={`translate(${p.x},${p.y})`}
                    onMouseEnter={() => setHover(n.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => setPicked(isPicked ? null : n.id)}
                  >
                    <rect x={-p.w / 2} y={-h / 2} width={p.w} height={h} rx={n.type === "section" ? 9 : 6}
                      stroke={color}
                      style={{ fill: n.type === "section" ? "var(--pv-section-fill)" : "var(--pv-node-fill)" }} />
                    {n.type === "document" && <rect x={-p.w / 2} y={-h / 2} width={3} height={h} fill={color} rx={1.5} />}
                    <text y={3.5} textAnchor="middle" className="pv-label" style={{ fill: n.type === "claim" ? "var(--text)" : color }}>
                      {label}
                    </text>
                    {(n.type === "metric" || n.type === "fact") && n.value && (
                      <text x={p.w / 2 - 6} y={3.5} textAnchor="end" className="pv-val">
                        {String(n.value).replace(/ 元$/, "")}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="pv-hint">悬停高亮邻接 · 点击查看对象 · 带引用的节点可直接打开四层证据</div>
        </div>

        <aside className="pv-detail">
          {!pickedNode && (
            <div className="pv-empty">
              <b>点一个节点</b>
              <p>左侧按章节过滤。选中的结论、指标或事实会在这里显示它的引用与下游对象。</p>
              <div className="pv-doclist">
                {(data.documents || []).map((d: any) => (
                  <div key={d.document_id} className="pv-doc">
                    <File size={12} />
                    <div>
                      <b>{d.title}</b>
                      <span>{d.pages} 页 · 校验码 {String(d.sha256 || "").slice(0, 10)}…</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {pickedNode && (
            <>
              <div className="pv-detail-h">
                <span className="pv-type" style={{ color: TYPE_COLOR[pickedNode.type], borderColor: TYPE_COLOR[pickedNode.type] }}>
                  {TYPE_LABEL[pickedNode.type]}
                </span>
              </div>
              <h3>{pickedNode.label}</h3>
              <div className="pv-sub">{pickedNode.sub}</div>
              {pickedNode.text && <div className="pv-quote">{pickedNode.text}</div>}
              {pickedNode.value && (
                <div className="pv-kv"><span>数值</span><b className="mono">{pickedNode.value}</b></div>
              )}
              {pickedNode.verdict && (
                <div className="pv-kv"><span>审核</span><b>{pickedNode.verdict}</b></div>
              )}
              <div className="pv-kv">
                <span>邻接</span><b>{neighbors[pickedNode.id]?.size || 0} 个对象</b>
              </div>
              {ev && (
                <div className="pv-ev">
                  <div className="pv-ev-h">证据预览</div>
                  {ev.document && (
                    <div className="pv-kv"><span>原件</span><b>{ev.document.title}</b></div>
                  )}
                  {ev.location?.page && (
                    <div className="pv-kv"><span>定位</span><b>P{ev.location.page} · {ev.location.cell_id || "—"}</b></div>
                  )}
                  {ev.formula?.text && (
                    <div className="pv-kv"><span>算式</span><b className="mono" style={{ fontSize: 10.5 }}>{ev.formula.text}</b></div>
                  )}
                  {ev.excerpt && <div className="pv-excerpt">“{truncate(ev.excerpt, 160)}”</div>}
                </div>
              )}
              {pickedNode.ref && (
                <button className="btn sm" style={{ marginTop: 10 }} onClick={() => onRef(pickedNode.ref)}>
                  打开四层证据 <ArrowUpRight size={11} />
                </button>
              )}
              {pickedNode.document_id && (
                <a className="btn sm" style={{ marginTop: 10 }} href={`/api/documents/${encodeURIComponent(pickedNode.document_id)}/file`} target="_blank" rel="noreferrer">
                  打开原件 PDF <ArrowUpRight size={11} />
                </a>
              )}
              {pickedNode.sha256 && (
                <div className="pv-sha mono">原件校验码 {String(pickedNode.sha256).slice(0, 26)}…</div>
              )}
            </>
          )}
        </aside>
      </div>

      <div className="note">{data.note}</div>
    </div>
  );
}
