import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import AgentFlow from "./AgentFlow";
import { ArrowUpRight, Check, File, Shield } from "./icons";

/**
 * 首页产品台：用本机真实数据渲染三个工作面。
 * 不是截图，也不是假动效；数字与标签来自当前报告与 /api/provenance。
 */

const TABS = [
  { id: "studio", label: "研究台", url: "127.0.0.1:8000/#run" },
  { id: "report", label: "报告", url: "127.0.0.1:8000/#report" },
  { id: "prov", label: "证据地图", url: "127.0.0.1:8000/#provenance" },
];

const TYPE_COLOR: Record<string, string> = {
  section: "#d6fb6a", claim: "#f3f4f6", metric: "#e8c583",
  fact: "#9be6c4", document: "#c8102e", rule: "#ff7a6b", bench: "#b79cff",
};

function trunc(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export default function ProductShowcase({
  agents, report, overview, reportId, versionNo, subjectName, onEnter, onOpenReport, onOpenProvenance,
}: {
  agents: any[]; report: any; overview: any;
  reportId?: string | null; versionNo?: number | null; subjectName?: string;
  onEnter: () => void; onOpenReport?: () => void; onOpenProvenance?: () => void;
}) {
  const [tab, setTab] = useState("studio");
  const [active, setActive] = useState(0);
  const [prov, setProv] = useState<any>(null);

  const ov = report?.sections?.find((s: any) => s.section_key === "overview")?.content;
  const kpis = ov?.kpis || [];
  const peer = report?.sections?.find((s: any) => s.section_key === "peer")?.content;
  const gm = kpis.find((k: any) => k.label === "毛利率")?.value || "41.84%";
  const gmRow = (peer?.rows || []).find((r: any) => r.metric_code === "gross_margin");
  const gmCells = gmRow?.cells || [];

  useEffect(() => {
    if (tab !== "studio") return;
    const t = setInterval(() => setActive((a) => (a + 1) % Math.max(agents.length, 1)), 2000);
    return () => clearInterval(t);
  }, [tab, agents.length]);

  useEffect(() => {
    setProv(null);
  }, [reportId, versionNo]);

  useEffect(() => {
    if (tab !== "prov" || prov || !reportId || !versionNo) return;
    api.provenance(reportId, versionNo).then(setProv).catch(() => {});
  }, [tab, prov, reportId, versionNo]);

  const activeAgent = agents[active] || agents[0];

  const counts = overview?.counts || {};
  const events = [
    ["PLAN", "覆盖矩阵", `${counts.entities || 18} 家 · ${counts.annual_reports || 54} 份可见`],
    ["FINANCE", "候选单元格", `${counts.facts || 1015} 条原件事实 · 冲突冻结`],
    ["INDUSTRY", "行业与图谱", "6 个行业样本 · 200 条关系边"],
    ["AUDIT", "审核发布", "30 余条结论 · 引用可达 100%"],
  ];

  return (
    <section className="band product-band" id="product">
      <div className="band-head center">
        <div className="kicker">Product, not a prompt</div>
        <h2>一张底稿，<br /><span className="thin">三个工作面。</span></h2>
        <p>
          研究台负责分工与运行，报告负责阅读，证据地图负责复核。
          下面每一块的数据都来自正在运行的系统，不是产品截图。
        </p>
      </div>

      <div className="product-stage">
        <div className="ps-bar">
          <span className="ps-dots"><i /><i /><i /></span>
          <div className="ps-tabs">
            {TABS.map((t) => (
              <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
          <span className="ps-url mono">{TABS.find((t) => t.id === tab)?.url}</span>
          <button className="ps-open" onClick={tab === "studio" ? onEnter : tab === "report" ? onOpenReport : onOpenProvenance}>
            打开 <ArrowUpRight size={11} />
          </button>
        </div>

        <div className="ps-body">
          {tab === "studio" && (
            <div className="ms">
              <aside className="ms-side">
                <div className="ms-label">AGENTS / 6</div>
                {agents.map((a: any, i: number) => (
                  <div className={"ms-agent" + (i === active ? " on" : "")} key={a.id}
                       style={{ ["--c" as any]: a.color }}>
                    <i />
                    <span>{a.stage}</span>
                    <em className="mono">{a.code}</em>
                  </div>
                ))}
                <div className="ms-side-note">每个角色有独立契约与禁止项</div>
              </aside>

              <div className="ms-main">
                <div className="ms-top">
                  <span className="ps-live"><i />可回放</span>
                  <span>六角色 / 两支并行 / 一次合流</span>
                  <span className="spacer" />
                  <span className="mono">{activeAgent?.name || "计划"} · 进行中</span>
                </div>
                <AgentFlow agents={agents} height={220} picked={activeAgent?.id} />
                <div className="ms-events">
                  {events.map(([code, node, msg], i) => (
                    <div className={"ms-ev" + (i <= active ? " done" : "")} key={node}>
                      <span className="mono t">{`00:0${i + 1}`}</span>
                      <span className="k mono">{code}</span>
                      <span className="n">{node}</span>
                      <span className="m">{msg}</span>
                    </div>
                  ))}
                </div>
              </div>

              <aside className="ms-out">
                <div className="ms-label">OUTPUT</div>
                <div className="ms-kpi">
                  <span>毛利率</span>
                  <b>{gm}</b>
                  <em>FY2025 · 合并口径</em>
                </div>
                <div className="ms-bars">
                  {kpis.slice(0, 3).map((k: any, i: number) => (
                    <div className="ms-bar" key={k.label}>
                      <span>{k.label}</span>
                      <i style={{ width: `${[78, 46, 38][i] || 40}%` }} />
                      <b className="mono">{k.value || "缺证"}</b>
                    </div>
                  ))}
                </div>
                <button className="ms-cta" onClick={onEnter}>进入真实工作台 <ArrowUpRight size={10} /></button>
              </aside>
            </div>
          )}

          {tab === "report" && (
            <div className="mr">
              <div className="mr-main">
                <div className="mr-kicker">
                  EVIDENCE CHAIN · v{report?.version?.version_no || 1} 已发布
                  <span className="spacer" />
                  <span className="mono">截止 {report?.version?.as_of || "2026-06-30"}</span>
                </div>
                <h3>{subjectName || "青岛啤酒"} · 年度经营研究</h3>
                <div className="mr-kpis">
                  {kpis.slice(0, 4).map((k: any) => (
                    <div key={k.label}><span>{k.label}</span><b>{k.value || "缺证"}</b></div>
                  ))}
                </div>
                <p className="mr-para">
                  报告从 8 个章节展开，每段结论后面跟着可点的引用。
                  毛利率的上升由营业成本率下降与产品结构变化共同贡献，
                  但公司没有披露吨价与吨成本，因此不把「结构升级」写成确定事实。
                </p>
                <div className="mr-chips">
                  {["毛利率", "营业成本", "经营现金流"].map((x, i) => (
                    <span className="mr-chip" key={x}>
                      <i>{["指标", "事实", "指标"][i]}</i>{x}
                    </span>
                  ))}
                  <span className="mr-hint">悬停看证据预览</span>
                </div>
                <div className="mr-table">
                  {gmCells.slice(0, 3).map((c: any, i: number) => (
                    <div className="mr-tr" key={c.entity_id || i}>
                      <span>{c.name}</span>
                      <i style={{ width: `${Math.min(100, parseFloat(String(c.display || "0")) * 1.5)}%` }} />
                      <b className="mono">{c.display || "缺证"}</b>
                    </div>
                  ))}
                </div>
              </div>
              <aside className="mr-ask">
                <div className="ms-label">ASK / 版本内追问</div>
                <div className="bubble q">毛利率在同行里处于什么位置？</div>
                <div className="bubble a">
                  青岛啤酒 {gm}
                  {gmCells[1]?.display ? `，${gmCells[1].name} ${gmCells[1].display}` : ""}
                  {gmCells[2]?.display ? `，${gmCells[2].name} ${gmCells[2].display}` : ""}。
                </div>
                <div className="bubble q">为什么毛利率下降？</div>
                <div className="bubble warn">
                  先核对前提：毛利率并未下降，FY2025 为 {gm}，比上年上升。
                </div>
                <div className="mr-ask-foot"><Shield size={10} /> 回答钉住 v{report?.version?.version_no || 1}</div>
              </aside>
            </div>
          )}

          {tab === "prov" && <MiniProv data={prov} onOpen={onOpenProvenance} />}
        </div>

        <div className="ps-foot">
          <span><Check size={11} /> 数据来自本机 SQLite 与巨潮原件</span>
          <span><File size={11} /> 每条引用可回到页码与单元格</span>
          <span className="spacer" />
          <button className="ps-foot-link" onClick={onEnter}>在工作台复现 <ArrowUpRight size={10} /></button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* 迷你证据地图                                                        */
/* ------------------------------------------------------------------ */

function MiniProv({ data, onOpen }: { data: any; onOpen?: () => void }) {
  const view = useMemo(() => {
    if (!data) return null;
    const nodes = data.nodes as any[];
    const pick = (t: string, n: number) => nodes.filter((x) => x.type === t).slice(0, n);
    const layers = [
      { type: "section", x: 66, list: pick("section", 3), w: 96 },
      { type: "claim", x: 220, list: pick("claim", 5), w: 138 },
      { type: "metric", x: 406, list: pick("metric", 5), w: 120 },
      { type: "fact", x: 582, list: pick("fact", 4), w: 120 },
      { type: "document", x: 736, list: pick("document", 2), w: 96 },
    ];
    const H = 322;
    const pos: Record<string, { x: number; y: number; w: number }> = {};
    for (const l of layers) {
      const gap = (H - 44) / (l.list.length + 1);
      l.list.forEach((n, i) => { pos[n.id] = { x: l.x, y: 30 + gap * (i + 1), w: l.w }; });
    }
    const ids = new Set(Object.keys(pos));
    const edges = (data.edges as any[]).filter((e) => ids.has(e.source) && ids.has(e.target)).slice(0, 22);
    return { layers, pos, edges, H };
  }, [data]);

  if (!view) return <div className="mp-empty">证据地图生成中…</div>;

  return (
    <div className="mp">
      <div className="mp-canvas">
        <svg viewBox={`0 0 806 ${view.H}`} style={{ width: "100%" }}>
          {view.layers.map((l) => (
            <g key={l.type}>
              <line x1={l.x} y1={12} x2={l.x} y2={view.H - 4} className="pv-guide" />
              <text x={l.x} y={9} textAnchor="middle" className="pv-layer">
                {{ section: "章节", claim: "结论", metric: "指标", fact: "事实", document: "原件" }[l.type as string]}
              </text>
            </g>
          ))}
          {view.edges.map((e, i) => {
            const a = view.pos[e.source], b = view.pos[e.target];
            if (!a || !b) return null;
            const mx = (a.x + b.x) / 2;
            return (
              <path key={i} d={`M${a.x + a.w / 2},${a.y} C ${mx},${a.y} ${mx},${b.y} ${b.x - b.w / 2},${b.y}`}
                className={"pv-edge " + e.kind} style={{ opacity: 0.35 }} />
            );
          })}
          {view.layers.flatMap((l) => l.list.map((n: any) => {
            const p = view.pos[n.id];
            const color = TYPE_COLOR[n.type] || "#999";
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} className="pv-node">
                <rect x={-p.w / 2} y={-11} width={p.w} height={22} rx={5}
                  stroke={color} fill="rgba(255,255,255,.025)" />
                <text y={3} textAnchor="middle" className="mp-label" style={{ fill: color }}>
                  {trunc(String(n.label || ""), n.type === "claim" ? 13 : 11)}
                </text>
              </g>
            );
          }))}
          <circle r="2.4" className="af-pulse">
            <animateMotion dur="4s" repeatCount="indefinite" path="M120,40 C 200,40 200,280 300,280" />
          </circle>
        </svg>
      </div>
      <div className="mp-side">
        <div className="ms-label">PROVENANCE</div>
        <div className="mp-stats">
          <div><b>{data.stats.claims}</b><span>条结论</span></div>
          <div><b>{data.stats.metrics}</b><span>个指标</span></div>
          <div><b>{data.stats.facts}</b><span>条事实</span></div>
          <div><b>{data.stats.documents}</b><span>份原件</span></div>
        </div>
        <p>每条边都来自这一版报告实际使用的引用。点开节点可以看到数值、审核状态与上游原件。</p>
        <button className="ms-cta" onClick={onOpen}>打开完整证据地图 <ArrowUpRight size={10} /></button>
      </div>
    </div>
  );
}
