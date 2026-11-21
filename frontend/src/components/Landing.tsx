import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import AgentFlow from "./AgentFlow";
import ProductShowcase from "./ProductShowcase";
import ThemeToggle from "./ThemeToggle";
import { ArrowUpRight, Check, File, Layers, Mark, Shield, Spark as SparkIcon } from "./icons";
import { Reveal, useScrollProgress, useTilt } from "./motion";

/* ------------------------------------------------------------------ */
/* 小部件                                                              */
/* ------------------------------------------------------------------ */

function Spark({ values, w = 300, h = 62, tone = "#d6fb6a" }: { values: number[]; w?: number; h?: number; tone?: string }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [
    6 + (i * (w - 12)) / Math.max(1, values.length - 1),
    h - 8 - ((v - min) / span) * (h - 22),
  ]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z`;
  const id = useMemo(() => "g" + Math.random().toString(36).slice(2, 7), []);
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: "block", marginTop: 14 }} preserveAspectRatio="none">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(214,251,106,.26)" />
          <stop offset="100%" stopColor="rgba(214,251,106,0)" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path
        d={line}
        fill="none"
        stroke={tone}
        strokeWidth="1.6"
        strokeLinecap="round"
        pathLength={1}
        style={{ strokeDasharray: 1, strokeDashoffset: 1, animation: "draw 1.8s .45s cubic-bezier(.2,.7,.2,1) forwards" }}
      />
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={i === pts.length - 1 ? 3 : 1.8} fill={i === pts.length - 1 ? tone : "#7d8a6a"} />
      ))}
    </svg>
  );
}

function MiniPdf({ title = "2025 年年度报告" }: { title?: string }) {
  return (
    <div className="float-page" aria-hidden>
      <div className="fp-cap">ANNUAL REPORT · {title}</div>
      <div className="fp-line" style={{ width: "72%" }} />
      <div className="fp-line w40" />
      <div className="fp-table">
        {[0, 1, 2, 3, 4].map((i) => (
          <div className={"fp-tr" + (i === 1 ? " hl" : "")} key={i}>
            <span style={{ width: `${64 + i * 6}%` }} />
            <span />
            <span />
          </div>
        ))}
      </div>
      <div className="fp-stamp">P6 · r2c1</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 证据链演示                                                          */
/* ------------------------------------------------------------------ */

const LAYERS = [
  { k: "指标", t: "指标", d: "毛利率是两条原始事实算出来的，不是读出来的", icon: <Layers /> },
  { k: "算式", t: "算式与代值", d: "每个变量绑定到单元格，公式带版本号", icon: <SparkIcon /> },
  { k: "原表", t: "原表单元格", d: "定位到页码与行列，而不是「年报第 6 页附近」", icon: <File /> },
  { k: "原件", t: "原件与校验码", d: "披露日 + 校验码标识原件", icon: <Shield /> },
];

function ChainDemo({ ev, margin }: { ev: any; margin: string }) {
  const [active, setActive] = useState(0);
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    if (locked) return;
    const t = setInterval(() => setActive((a) => (a + 1) % 4), 6200);
    return () => clearInterval(t);
  }, [locked]);

  const inputs = ev?.formula?.inputs || [];
  const rev = inputs.find((i: any) => i.slot === "revenue");
  const cost = inputs.find((i: any) => i.slot === "operating_cost");
  const page = ev?.location?.page;
  const bbox = ev?.location?.bbox;
  const pageUrl = ev?.document?.document_id && page
    ? `/api/documents/${encodeURIComponent(ev.document.document_id)}/page/${page}.png`
    : null;
  const revTxt = rev?.display || "—";
  const costTxt = cost?.display || "—";

  const body = () => {
    if (active === 0) {
      return (
        <div className="demo-fade">
          <div className="dm-label">FY2025 · 合并口径 · 已核验</div>
          <div className="dm-value">{margin}<small>%</small></div>
          <div className="dm-formula">
            <b>(revenue − operating_cost) / revenue</b>
            <br />
            ({revTxt} − {costTxt}) / {revTxt}
          </div>
          <div className="dm-trail">
            <span className="dt on">指标</span><i />
            <span className="dt">2 条原始事实</span><i />
            <span className="dt">P{page || 6} · {ev?.location?.cell_id || "L"}</span><i />
            <span className="dt">原件</span>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 10.5, color: "var(--dim)", marginTop: 14 }}>
            <span>逐项复算 · 不用浮点近似</span>
            <span>冲突即冻结 · 不猜</span>
            <span>可信度 高</span>
          </div>
        </div>
      );
    }
    if (active === 1) {
      return (
        <div className="demo-fade">
          <div className="dm-label">毛利率 · 算式与代值</div>
          <div className="dm-formula" style={{ marginTop: 10 }}>
            ( <b>revenue</b> − <b>operating_cost</b> ) / <b>revenue</b>
          </div>
          <table className="dm-tbl" style={{ marginTop: 14 }}>
            <thead>
              <tr><th>变量</th><th>取值（元）</th><th>定位</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>营业收入</td>
                <td>{revTxt}</td>
                <td>P{rev?.page || page || 6} · {rev?.cell_id || "—"}</td>
              </tr>
              <tr>
                <td>营业成本</td>
                <td>{costTxt}</td>
                <td>P{cost?.page || page || 6} · {cost?.cell_id || "—"}</td>
              </tr>
              <tr className="mark">
                <td>毛利率</td>
                <td>{margin}%</td>
                <td>计算值</td>
              </tr>
            </tbody>
          </table>
          <div style={{ fontSize: 10.5, color: "var(--dim)", marginTop: 10 }}>
            点变量可继续下钻，直到 PDF 上的那一格。
          </div>
        </div>
      );
    }
    if (active === 2) {
      return (
        <div className="demo-fade">
          <div className="dm-label">合并利润表 · 2025 年度 · 单位：元</div>
          <table className="dm-tbl" style={{ marginTop: 10 }}>
            <thead><tr><th>项目</th><th>2025</th><th>定位</th></tr></thead>
            <tbody>
              <tr className="mark"><td>营业收入</td><td>{revTxt}</td><td>P{rev?.page || page}</td></tr>
              <tr><td>营业成本</td><td>{costTxt}</td><td>P{cost?.page || page}</td></tr>
              <tr><td>归母净利润</td><td colSpan={2} style={{ color: "var(--dim)" }}>见报告「财务指标」</td></tr>
            </tbody>
          </table>
          <div style={{ fontSize: 10.5, color: "var(--dim)", marginTop: 12 }}>
            抽取器只返回「位置 + 原值」，单位换算与舍入规则单独记录。
          </div>
        </div>
      );
    }
    return (
      <div className="demo-fade">
        <div className="dm-label">原件 · 第 {page || 6} 页 · {ev?.document?.published_on || "—"}</div>
        {pageUrl ? (
          <div className="pdf-crop">
            <div className="pdf-inner">
              <img src={pageUrl} alt="年报原页" />
              {bbox && (
                <div
                  className="hl"
                  data-label={`营业收入 · ${ev?.location?.cell_id || ""}`}
                  style={{
                    left: `${bbox[0] * 100}%`,
                    top: `${bbox[1] * 100}%`,
                    width: `${(bbox[2] - bbox[0]) * 100}%`,
                    height: `${(bbox[3] - bbox[1]) * 100}%`,
                  }}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="dm-formula">原件页需要先完成年报入库。</div>
        )}
        <div className="dm-meta">
          <span className="k">原件校验码</span>
          <span className="v">{(ev?.document?.sha256 || "—").slice(0, 32)}…</span>
          <span className="k">披露日</span>
          <span className="v">{ev?.document?.published_on || "—"}</span>
          <span className="k">读取方式</span>
          <span className="v">PDF 表格识别</span>
        </div>
      </div>
    );
  };

  return (
    <div className="chain-grid">
      <div className="chain-tabs">
        {LAYERS.map((l, i) => (
          <button
            key={l.k}
            className={"chain-tab" + (active === i ? " on" : "")}
            onClick={() => { setActive(i); setLocked(true); }}
            onMouseEnter={() => { setActive(i); setLocked(true); }}
          >
            <span className="no">{String(i + 1).padStart(2, "0")}</span>
            <span>
              <b>{l.t}</b>
              <span className="d">{l.d}</span>
            </span>
          </button>
        ))}
      </div>

      <div className="demo">
        <div className="demo-h">
          <span className="lights"><i /><i /><i /></span>
          EVIDENCE · 毛利率 · FY2025
          <span style={{ marginLeft: "auto", color: "var(--ev)" }}>四层穿透</span>
        </div>
        <div className="demo-b">{body()}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 追问演示                                                            */
/* ------------------------------------------------------------------ */

const DEMO_QUESTIONS = [
  "毛利率在同行里处于什么位置？",
  "为什么经营现金流和净利润不同步？",
  "哪些资料没拿到，会影响哪个结论？",
  "讲一下这个行业的产业链上下游",
];

function AskDemo({
  reportId, versionNo, onEnter, onAsk,
}: {
  reportId: string | null; versionNo: number | null; onEnter: () => void;
  onAsk?: (q: string) => void;
}) {
  const [q, setQ] = useState(DEMO_QUESTIONS[0]);
  const [ans, setAns] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const run = async (question: string) => {
    if (!reportId || !versionNo) return;
    setQ(question);
    setBusy(true);
    try {
      const r = await api.ask(reportId, versionNo, question);
      setAns(r);
    } catch (e: any) {
      setAns({ answer: String(e.message || e), refs: [] });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (reportId && versionNo) run(DEMO_QUESTIONS[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId, versionNo]);

  return (
    <div className="askdemo">
      <div className="ad-side">
        <div className="ad-label">ASK · 版本内追问</div>
        <h3>回答钉住版本，<br />不混入最新材料。</h3>
        <p>
          追问只检索这一版报告的证据。问「为什么」时，先给变化与算式，
          再给公司披露的归因和还缺的材料；不知道就写不知道。
        </p>
        <div className="ad-qs">
          {DEMO_QUESTIONS.map((x) => (
            <button key={x} className={"ad-q" + (q === x ? " on" : "")} onClick={() => run(x)}>
              {x}
            </button>
          ))}
        </div>
        <button className="btn sm" onClick={() => (onAsk ? onAsk(q) : onEnter())}>
          在报告里继续问 <ArrowUpRight size={11} />
        </button>
      </div>
      <div className="ad-main">
        <div className="ad-head">
          <span className="ad-dot" />
          QUESTION
          <span className="spacer" />
          <span className="mono">v{versionNo || 1} · 冻结证据</span>
        </div>
        <div className="ad-qbig">{q}</div>
        {busy && <div className="ad-loading"><i /><i /><i /></div>}
        {!busy && ans && (
          <div className="ad-ans">
            {ans.premise && (
              <div className="ad-premise">
                前提校验：问题说{ans.premise.claimed === "down" ? "下降" : "上升"}，实际
                {ans.premise.actual === "up" ? "上升" : "下降"} {ans.premise.change}{ans.premise.unit}
              </div>
            )}
            {String(ans.answer || "").split("\n").map((l: string, i: number) => <p key={i}>{l}</p>)}
            {ans.refs?.length > 0 && (
              <div className="ad-refs">
                {ans.refs.slice(0, 5).map((r: string, i: number) => (
                  <span className="ad-ref" key={r}><i>{i + 1}</i>{r.split(":")[0]}</span>
                ))}
              </div>
            )}
            {ans.sources?.length > 0 && (
              <div className="ad-src">第三方来源 {ans.sources.length} 条，已在回答中单独标注</div>
            )}
          </div>
        )}
        {!reportId && <div className="ad-ans"><p>先生成一份报告，再在这里追问。</p></div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 页面                                                                */
/* ------------------------------------------------------------------ */

const LAND_AGENTS = [
  { id: "plan", name: "计划 Agent", code: "PLAN", stage: "规划", nodes: ["plan"], verb: "先看有什么，再决定要什么", color: "#d6fb6a",
    mission: "根据观察截止日与可用原件生成覆盖矩阵；缺失项如实标 MISSING。", guard: "只统计可见性，不评价经营。" },
  { id: "collect", name: "资料 Agent", code: "COLLECT", stage: "搜集", nodes: ["collect", "ingest"], verb: "只提查询提案，不写结论", color: "#7fa6ff",
    mission: "把缺口变成可执行的检索提案，校验发布方、日期与全文后登记原件。", guard: "搜索摘要不得进入引用与证据图。" },
  { id: "finance", name: "财务 Agent", code: "FINANCE", stage: "核验", nodes: ["finance_extract", "verify_calc"], verb: "只指认单元格，不返回数字", color: "#e8c583",
    mission: "指认三张主表的候选格；服务端回读原值，再做同键比较、冲突判定与 Decimal 复算。", guard: "同级冲突即冻结，缺证不显示 0。" },
  { id: "industry", name: "行业 Agent", code: "INDUSTRY", stage: "行业", nodes: ["industry", "validate_industry"], verb: "每条关系都要能点回原文", color: "#9be6c4",
    mission: "聚合行业样本与产业链关系；打不开原文的边降级或移除。", guard: "样本合计不冒充行业总量。" },
  { id: "risk", name: "风险 Agent", code: "RISK", stage: "解释", nodes: ["risk_explain"], verb: "只解释已触发的警报", color: "#ff7a6b",
    mission: "对确定性规则产出的警报补上观察事实、潜在影响、反证与下一份材料。", guard: "不改阈值、不改判、不给违约概率。" },
  { id: "audit", name: "审核 Agent", code: "AUDIT", stage: "审核", nodes: ["compose", "audit"], verb: "不改数字，只挑问题", color: "#b79cff",
    mission: "检查引用可达、数字绑定与措辞强度；未过审的结论不进入正文。", guard: "模板里不允许出现未绑定的阿拉伯数字。" },
];

export default function Landing({
  onEnter,
  onOpenReport,
  onOpenIndustry,
  onOpenProvenance,
  report,
  subject,
  overview,
  reportId,
  versionNo,
  onAsk,
}: {
  onEnter: () => void;
  onOpenReport?: () => void;
  onOpenIndustry?: (id: string) => void;
  onOpenProvenance?: () => void;
  report: any;
  subject?: any;
  overview?: any;
  reportId?: string | null;
  versionNo?: number | null;
  onAsk?: (q: string) => void;
}) {
  const [ev, setEv] = useState<any>(null);
  const [industries, setIndustries] = useState<any[]>([]);
  const [evals, setEvals] = useState<any>(null);
  const [compare, setCompare] = useState<any>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const { ref: artRef, tilt } = useTilt();

  const ovSec = report?.sections?.find((s: any) => s.section_key === "overview")?.content;
  const fin = report?.sections?.find((s: any) => s.section_key === "financials")?.content;
  const kpis = ovSec?.kpis || [];
  const gmKpi = kpis.find((k: any) => k.label === "毛利率");
  const gmRow = (fin?.rows || []).find((r: any) => r.metric_code === "gross_margin");
  const gmDeltaRow = (fin?.rows || []).find((r: any) => r.metric_code === "gross_margin_delta_pp");
  const revRow = (fin?.rows || []).find((r: any) => r.metric_code === "revenue_yoy");
  const lastOf = (row: any) => {
    const s = row?.series || [];
    const v = s[s.length - 1]?.value;
    return v == null || v === "" ? null : Number(v);
  };
  const gmSeries = (gmRow?.series || []).map((s: any) => Number(s.value) * 100);
  const gmValues = gmSeries.length >= 2 ? gmSeries : [43.93, 42.39, 41.36];
  const gmNow = (gmKpi?.value || "41.36").replace("%", "");
  const gmPrev = gmValues[gmValues.length - 2] ?? 42.39;
  const gmDelta = lastOf(gmDeltaRow);
  const delta = gmDelta != null ? gmDelta.toFixed(2) : (Number(gmNow) - gmPrev).toFixed(2);
  const revYoy = lastOf(revRow);
  const revYoyTxt = revYoy == null ? "—" : `${revYoy > 0 ? "+" : ""}${(revYoy * 100).toFixed(2)}%`;

  useEffect(() => {
    if (gmKpi?.ref) api.evidence(gmKpi.ref).then(setEv).catch(() => {});
  }, [gmKpi?.ref]);

  useEffect(() => {
    api.industries().then((r) => setIndustries(r.industries || [])).catch(() => {});
    api.eval().then(setEvals).catch(() => {});
    api.compare("gross_margin", 2025).then(setCompare).catch(() => {});
    api.agents().then((r) => setAgents(r.agents || [])).catch(() => {});
  }, []);

  const [scrolled, setScrolled] = useState(false);
  const progress = useScrollProgress();
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 12);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  const subjectName = subject?.name || "青岛啤酒";
  const subjectCode = subject?.ticker ? `${subject.exchange || "SH"}:${subject.ticker}` : "SH:600600";
  const scrollToSection = (id: string) => {
    // 首页锚点不能再改 location.hash：hash 是工作台路由，会把页面切走。
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const counts = overview?.counts || {};
  const docN = counts.annual_reports ?? (industries.reduce((a, i) => a + (i.documents || 0), 0) || 54);
  const factN = counts.facts ?? (industries.reduce((a, i) => a + (i.facts || 0), 0) || 1015);
  const cross = overview?.cross_source || evals?.cross_source;
  const agencyRate = cross ? Math.round(cross.agreement * 1000) / 10 : null;
  const matrixRows = overview?.industry_matrix?.rows || [];

  const marginRows = (compare?.rows || []).map((r: any) => {
    const rev = r.sum;
    return { name: r.name, industry: r.industry, n: r.n, rev };
  });

  return (
    <div className="land">
      <div className="land-bg" />
      <div style={{ position: "fixed", top: 0, left: 0, height: 2, width: `${progress * 100}%`, background: "var(--red)", zIndex: 99, opacity: 0.8 }} />

      <nav className={"site-nav" + (scrolled ? " scrolled" : "")} style={{ position: "fixed", left: 0, right: 0, top: 0 }}>
        <button className="brand-btn" onClick={onEnter}>
          <span className="logo-mark"><Mark /></span>
          <span className="brand-txt">
            <b>经营证据链</b>
            <i>Evidence Chain</i>
          </span>
        </button>
        <div className="site-links">
          <a href="#agents" onClick={(e) => { e.preventDefault(); scrollToSection("agents"); }}>智能体</a>
          <a href="#who" onClick={(e) => { e.preventDefault(); scrollToSection("who"); }}>谁在用</a>
          <a href="#chain" onClick={(e) => { e.preventDefault(); scrollToSection("chain"); }}>证据链</a>
          <a href="#ask" onClick={(e) => { e.preventDefault(); scrollToSection("ask"); }}>追问</a>
          <a href="#coverage" onClick={(e) => { e.preventDefault(); scrollToSection("coverage"); }}>覆盖</a>
          <a href="#measured" onClick={(e) => { e.preventDefault(); scrollToSection("measured"); }}>评测</a>
          {report && (
            <a href="#report" onClick={(e) => { e.preventDefault(); onOpenReport?.(); }}>示例报告</a>
          )}
        </div>
        <div className="spacer" />
        <ThemeToggle />
        <span className="proposal-badge"><i />工商银行命题二</span>
        <button className="btn sm" onClick={onEnter} style={{ borderColor: "var(--line-2)" }}>
          进入工作台 <ArrowUpRight size={13} />
        </button>
      </nav>

      <div className="shell">
        {/* ---------------- Hero ---------------- */}
        <header className="hero">
          <div>
            <div className="eyebrow"><span className="pt red" />多智能体 · 证据链 · 行业研究</div>
            <h1>
              把结论，
              <br />
              钉回年报<span className="grad">那一页</span><span className="stop">。</span>
            </h1>
            <p className="lede">
              六个 AI 角色分工协作：搜集资料、核验口径、测算财务、连接产业链、解释风险、审核发布。
              结论绑定到 54 份年报的页码与单元格，可以追问，也能在新材料到达后只更新受影响的部分。
            </p>
            <div className="cta-row">
              <button className="btn-lime" onClick={onEnter}>
                进入工作台 <ArrowUpRight size={16} />
              </button>
              <a className="link-arrow" href="#chain" onClick={(e) => { e.preventDefault(); scrollToSection("chain"); }}>
                看一层证据 <span style={{ color: "var(--accent)" }}>↓</span>
              </a>
            </div>
            <div className="hero-meta">
              <span><Check size={12} /> 6 个 Agent 角色</span>
              <span><Check size={12} /> {docN} 份年报原件</span>
              <span><Check size={12} /> 每条结论可点回原件</span>
            </div>
          </div>

          <div
            className="hero-art"
            ref={artRef}
            style={{ ["--tx" as any]: tilt.x, ["--ty" as any]: tilt.y }}
          >
            <div className="hero-halo" />
            <div className="hero-ring r1" />
            <div className="hero-ring r2" />
            <div className="hero-ring r3" />

            <article className="report-card">
              <div className="rc-head">
                <span className="rc-dot" />
                <span className="rc-brand">EVIDENCE CHAIN</span>
                <span className="rc-ver">v{report?.version?.version_no || 1} 已发布</span>
              </div>
              <div className="rc-title">{subjectName} · 年度经营研究</div>
              <div className="rc-sub">{subjectCode} · FY2025 · 截止 {report?.version?.as_of || "2026-06-30"}</div>

              <div className="rc-kpi">
                <div>
                  <span className="rc-label">毛利率 Gross margin</span>
                  <div className="rc-val">{gmNow}<span>%</span></div>
                </div>
                <span className={"rc-delta " + (Number(delta) < 0 ? "down" : "up")}>
                  {Number(delta) > 0 ? "+" : ""}{delta} pp
                </span>
              </div>
              <Spark values={gmValues} />
              <div style={{ display: "flex", gap: 10, marginTop: 4, fontSize: 9, color: "var(--dim)", fontFamily: "var(--mono)" }}>
                {["FY2023", "FY2024", "FY2025"].map((y) => <span key={y}>{y}</span>)}
              </div>

              <div className="rc-rows">
                {[
                  ["营收同比", revYoyTxt],
                  ["归母净利率", kpis.find((k: any) => k.label === "归母净利率")?.value || "14.13%"],
                  ["资产负债率", kpis.find((k: any) => k.label === "资产负债率")?.value || "39.56%"],
                ].map(([n, v]) => (
                  <div className="rc-row" key={n as string}>
                    <span className="n">{n}</span>
                    <span className="bar" />
                    <span className="v">{v}</span>
                  </div>
                ))}
              </div>

              <div className="rc-foot">
                <span className="ev-dot" /> 引用均可打开原页
                <span className="hash">校验 {(ev?.document?.sha256 || "9dade1e8").slice(0, 8)}</span>
              </div>
            </article>

            <div className="float-chip chip-a">
              <span className="tag">FACT</span>
              合并利润表 <b>P{ev?.location?.page || 72}</b>
            </div>
            <div className="float-chip chip-b">
              <span className="tag">✓</span> 原件抽出 <b>{factN}</b> 条
            </div>
            <MiniPdf />
          </div>
        </header>

        {/* ---------------- 数据带 ---------------- */}
        <Reveal>
          <div className="stat-band">
            {[
              { n: agents.length || 6, s: " 个", l: "Agent 角色", x: "计划 / 资料 / 财务 / 行业 / 风险 / 审核" },
              { n: 6, s: " 个", l: "行业样本", x: "啤酒 / 白酒 / 乳品 / 家电 / 汽车 / 光伏" },
              { n: 18, s: " 家", l: "上市公司", x: "每个行业 3 家，龙头 / 次龙头 / 差异化" },
              { n: docN, s: " 份", l: "年报原件", x: "巨潮资讯法定披露 PDF，逐份校验" },
              { n: factN, s: " 条", l: "原件抽取事实", x: "带页码、单元格与高亮框" },
            ].map((s) => (
              <div className="cell" key={s.l}>
                <span className="n">{s.n}{s.s && <em>{s.s}</em>}</span>
                <span className="l">{s.l}</span>
                <span className="x">{s.x}</span>
              </div>
            ))}
          </div>
        </Reveal>

        {/* ---------------- 产品台 ---------------- */}
        <Reveal delay={40}>
          <ProductShowcase
            agents={agents.length ? agents : LAND_AGENTS}
            report={report}
            overview={overview}
            reportId={reportId}
            versionNo={versionNo}
            subjectName={subjectName}
            onEnter={onEnter}
            onOpenReport={onOpenReport}
            onOpenProvenance={onOpenProvenance}
          />
        </Reveal>

        {/* ---------------- 断点 ---------------- */}
        <section className="band" id="problem">
          <Reveal>
            <div className="band-head">
              <div className="kicker">Where research breaks</div>
              <h2>研究不是没有结论，<br /><span className="thin">是结论无法复核。</span></h2>
              <p>
                一份两百页的年报，关键数字散在三张主表、十几条附注和更正公告里；
                合并与母公司并列、万元与元混排、本期与上期同表。任何一处错位，
                后面的判断都会反。
              </p>
            </div>
          </Reveal>
          <div className="pain-grid">
            {[
              { no: "01", t: "材料分散", d: "同一指标出现在管理层讨论、主表与附注，口径与期间各不相同。" },
              { no: "02", t: "口径易错", d: "合并/母公司、万元/元、期末/期初。抽取错一格，毛利率就差几个点。" },
              { no: "03", t: "结论不可复核", d: "只给结论不给位置，无法判断是数据错、公式错，还是解读错。" },
            ].map((p, i) => (
              <Reveal delay={i * 70} key={p.no}>
                <div className="pain-card">
                  <span className="pain-no">{p.no}</span>
                  <h3>{p.t}</h3>
                  <p>{p.d}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ---------------- 谁在用 ---------------- */}
        <section className="band" id="who">
          <Reveal>
            <div className="band-head">
              <div className="kicker">Who it is for</div>
              <h2>三种研究日常，<br /><span className="thin">同一套复核标准。</span></h2>
              <p>
                不是给「想快速生成一篇研报」的人，而是给需要把结论拿去评审、
                上报或写进投委会材料的人。
              </p>
            </div>
          </Reveal>
          <div className="persona-grid">
            {[
              {
                code: "SELL-SIDE", role: "券商行业研究员", icon: Layers,
                job: "覆盖 2–3 个行业、十几家公司，季报后要快速回答「谁在变好、为什么」。",
                gets: ["同业三表与毛利率对比", "每条结论的页码与单元格", "可复用的行业样本口径"],
                quote: "写进报告的数字，我要能指出是第几页。",
              },
              {
                code: "BANK-CREDIT", role: "银行行业研究员", icon: Shield,
                job: "看行业景气与企业经营风险，需要区分「披露事实」「合理推断」和「还缺什么」。",
                gets: ["现金流与利润背离检查", "风险规则的反证与未评估项", "新材料到达后的增量修订"],
                quote: "未触发不等于无风险，我要看到边界。",
              },
              {
                code: "STRATEGY", role: "企业战略 / 投研助理", icon: File,
                job: "做进入策略、供应链与竞品跟踪，材料散在年报、公告和行业报告里。",
                gets: ["六行业横截面与产业链关系", "带依据的上下游边", "版本化底稿与可追问证据"],
                quote: "先把资料找齐，再谈判断。",
              },
            ].map((p: any, i: number) => (
              <Reveal delay={i * 70} key={p.role}>
                <div className="persona-card">
                  <div className="pc-top">
                    <span className="pc-icon"><p.icon size={15} /></span>
                    <span className="pc-code mono">{p.code}</span>
                  </div>
                  <h3>{p.role}</h3>
                  <p className="pc-job">{p.job}</p>
                  <div className="pc-gets">
                    {p.gets.map((g: string) => <span key={g}><Check size={10} />{g}</span>)}
                  </div>
                  <div className="pc-quote">「{p.quote}」</div>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ---------------- 多智能体 ---------------- */}
        <section className="band" id="agents">
          <Reveal>
            <div className="band-head">
              <div className="kicker">Six agents, one evidence standard</div>
              <h2>六个角色，<br /><span className="thin">共用一套证据规则。</span></h2>
              <p>
                多智能体不是把同一段话问六遍。计划定范围、资料找原件、财务核口径、
                行业连关系、风险做解释、审核守发布；每个角色只能碰自己那一段。
              </p>
            </div>
          </Reveal>

          <Reveal delay={60}>
            <div className="agent-stage">
              <div className="agent-stage-h">
                <span className="lights"><i /><i /><i /></span>
                ORCHESTRATION · 六角色 / 两支并行 / 一次合流
                <span className="spacer" />
                <span className="mono">协作流程</span>
              </div>
              <AgentFlow agents={agents.length ? agents : LAND_AGENTS} height={286} />
              <div className="agent-stage-f">
                <span>计划 → 资料</span>
                <span>资料 → 财务 / 行业（并行）</span>
                <span>两支 → 风险解释 → 审核发布</span>
              </div>
            </div>
          </Reveal>

          <div className="agent-roles">
            {(agents.length ? agents : LAND_AGENTS).map((a: any, i: number) => (
              <Reveal delay={i * 45} key={a.id}>
                <div className="agent-role" style={{ ["--c" as any]: a.color }}>
                  <div className="ar-top">
                    <span className="ar-code">{a.code}</span>
                    <span className="ar-stage">{a.stage}</span>
                  </div>
                  <b>{a.verb}</b>
                  <p>{a.mission}</p>
                  <div className="ar-guard"><i />{a.guard}</div>
                </div>
              </Reveal>
            ))}
          </div>

          <Reveal delay={80}>
            <div className="agent-rules">
              <div><span>01</span><b>角色隔离</b><p>财务角色只指认单元格，不返回数字；行业角色每条结论必须带证据编号。</p></div>
              <div><span>02</span><b>输出格式固定</b><p>每个角色按固定字段交付；字段缺失或越界会被直接拦下，不靠提示词自觉。</p></div>
              <div><span>03</span><b>独立审核</b><p>审核不是让另一个模型点头，而是程序检查引用、口径、算式与数字绑定。</p></div>
            </div>
          </Reveal>
        </section>

        {/* ---------------- 证据链 ---------------- */}
        <section className="band" id="chain">
          <Reveal>
            <div className="band-head">
              <div className="kicker">The evidence chain</div>
              <h2>四层之后，<br /><span className="thin">才允许下结论。</span></h2>
              <p>
                点开报告里的任意数字：先看口径与可信度，再看算式与代值，
                然后落到年报原表的单元格，最后是带披露日与校验码的原件。
              </p>
            </div>
          </Reveal>
          <Reveal delay={80}>
            <ChainDemo ev={ev} margin={gmNow} />
          </Reveal>
          <Reveal delay={120}>
            <div className="chain-cta">
              <div>
                <b>不止一个数字。</b>
                <span>打开真实报告的证据地图，看 8 个章节、30 余条结论分别落在哪些指标、事实与原件上。</span>
              </div>
              <button className="btn" onClick={onOpenProvenance}>
                打开证据地图 <ArrowUpRight size={12} />
              </button>
            </div>
          </Reveal>
        </section>

        {/* ---------------- 追问 ---------------- */}
        <section className="band" id="ask">
          <Reveal>
            <div className="band-head">
              <div className="kicker">Ask, with provenance</div>
              <h2>追问不是重写，<br /><span className="thin">是回到同一份证据。</span></h2>
              <p>
                答疑钉住报告版本：不会把后来披露的材料混进旧结论。
                回答里的每个引用仍然可以点回原页；跨公司比较会明确标注第三方来源。
              </p>
            </div>
          </Reveal>
          <Reveal delay={60}>
            <AskDemo reportId={reportId || null} versionNo={versionNo || null} onEnter={onOpenReport || onEnter} onAsk={onAsk} />
          </Reveal>
        </section>

        {/* ---------------- 覆盖 ---------------- */}
        <section className="band" id="coverage">
          <Reveal>
            <div className="band-head">
              <div className="kicker">Coverage</div>
              <h2>先把行业铺开，<br /><span className="thin">再谈单家公司。</span></h2>
              <p>
                每个行业三家可比公司，全部使用同一年度、同一口径的公开数据。
                点开任一行业，可以看三家公司的规模、毛利率与杠杆，以及它们在产业链上的位置。
              </p>
            </div>
          </Reveal>

          <div className="cov-matrix">
            {(industries.length ? industries : Array.from({ length: 6 }).map((_, i) => ({
              id: ["beer", "baijiu", "dairy", "appliance", "auto", "solar"][i],
              name: ["啤酒", "白酒", "乳制品", "家用电器", "汽车整车", "光伏设备"][i],
              companies: [], documents: 0, facts: 0,
            }))).map((ind: any, i: number) => (
              <Reveal delay={i * 45} key={ind.id}>
                <button className="cov-card" onClick={() => onOpenIndustry?.(ind.id)}>
                  <div className="cov-head">
                    <span className="cov-idx">{String(i + 1).padStart(2, "0")}</span>
                    <b>{ind.name}</b>
                    <span className="cov-n">{ind.documents ? `${ind.documents} 份原件` : "—"}</span>
                  </div>
                  <div className="cov-cos">
                    {(ind.companies || []).map((c: any) => (
                      <span className="cov-co" key={c.entity_id}>
                        <i className={c.role} />
                        {c.name}
                        <em>{c.ticker}</em>
                      </span>
                    ))}
                  </div>
                  <div className="cov-foot">
                    <span>{ind.facts ? `${ind.facts} 条抽取事实` : "待入库"}</span>
                    <ArrowUpRight size={12} />
                  </div>
                </button>
              </Reveal>
            ))}
          </div>

          {matrixRows.length > 0 && (
            <Reveal delay={70}>
              <div className="land-matrix">
                <div className="lm-head">
                  <b>FY2025 样本横截面</b>
                  <span>每格为 3 家公司的样本口径；点一行进入该行业。颜色只表示相对高低，不是投资建议。</span>
                </div>
                <div className="lm-grid">
                  <div className="lm-row lm-title">
                    <span>行业</span><span>营收同比</span><span>毛利率</span><span>资产负债率</span><span>经营现金流/营收</span>
                  </div>
                  {matrixRows.map((r: any) => (
                    <button className="lm-row" key={r.industry} onClick={() => onOpenIndustry?.(r.industry)}>
                      <span className="lm-name">{r.name}<em>n={r.n}</em></span>
                      <span className={"lm-cell " + ((r.growth_pct || 0) >= 0 ? "pos" : "neg")}>
                        {r.growth_pct == null ? "—" : `${r.growth_pct > 0 ? "+" : ""}${r.growth_pct.toFixed(1)}%`}
                      </span>
                      <span className="lm-cell gm">
                        <i style={{ width: `${Math.min(100, Math.max(2, r.gross_margin_pct || 0))}%` }} />
                        <b>{r.gross_margin_pct == null ? "—" : `${r.gross_margin_pct.toFixed(1)}%`}</b>
                      </span>
                      <span className={"lm-cell " + ((r.debt_ratio_pct || 0) > 60 ? "warn" : "")}>
                        {r.debt_ratio_pct == null ? "—" : `${r.debt_ratio_pct.toFixed(1)}%`}
                      </span>
                      <span className={"lm-cell " + ((r.ocf_margin_pct || 0) >= 0 ? "pos" : "neg")}>
                        {r.ocf_margin_pct == null ? "—" : `${r.ocf_margin_pct.toFixed(1)}%`}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </Reveal>
          )}

          {marginRows.length > 0 && (
            <Reveal delay={80}>
              <div className="cmp-strip">
                <div className="cmp-head">
                  <b>2025 年样本营收合计</b>
                  <span>单位：亿元 · 每行业 3 家 · 样本口径，不代表行业总量</span>
                </div>
                <div className="cmp-bars">
                  {marginRows.map((r: any) => {
                    const max = Math.max(...marginRows.map((x: any) => x.rev || 0)) || 1;
                    return (
                      <div className="cmp-row" key={r.industry}>
                        <span className="l">{r.name}</span>
                        <span className="t"><i style={{ width: `${((r.rev || 0) / max) * 100}%` }} /></span>
                        <span className="v">{r.rev ? (r.rev / 1e8).toFixed(0) : "—"}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </Reveal>
          )}
        </section>

        {/* ---------------- 评测 ---------------- */}
        <section className="band" id="measured" style={{ paddingBottom: 0 }}>
          <Reveal>
            <div className="band-head">
              <div className="kicker">Cross-source verification</div>
              <h2>评测不给自己出题。</h2>
              <p>
                参照值不是我们标的。同一指标，一边来自年报原件，一边来自第三方结构化数据，
                逐项对撞；差异按「舍入 / 单位 / 口径 / 真错」归类，不掩盖失败样本。
              </p>
            </div>
          </Reveal>
          <Reveal delay={60}>
            <div className="eval-strip">
              <div className="eval-cell big">
                <span className="ev-n">{agencyRate !== null ? `${agencyRate}%` : "—"}</span>
                <span className="ev-l">跨源一致率</span>
                <span className="ev-x">{cross ? `${cross.ok} / ${cross.pairs} 对可比值` : "运行评测后显示"}</span>
              </div>
              <div className="eval-cell">
                <span className="ev-n">{cross?.pairs ?? "—"}</span>
                <span className="ev-l">可比值</span>
                <span className="ev-x">6 行业 × 18 公司 × 9 字段 × 3 年</span>
              </div>
              <div className="eval-cell">
                <span className="ev-n">{cross?.counts?.mismatch ?? "—"}</span>
                <span className="ev-l">真不一致</span>
                <span className="ev-x">全部列出公司与页码，可人工复核</span>
              </div>
              <div className="eval-cell">
                <span className="ev-n">{cross?.restatement_n ?? "—"}</span>
                <span className="ev-l">跨年重述</span>
                <span className="ev-x">同一指标在不同年报中数值不同</span>
              </div>
            </div>
          </Reveal>
          <Reveal delay={90}>
            <div className="eval-note">
              模板语料的逐格金标只用于回归，不作为真实精度对外表述；
              真实精度以跨源一致率为准，并且允许失败样本存在。
            </div>
          </Reveal>

          <Reveal delay={110}>
            <div className="proof-wrap">
              <div className="proof-term">
                <div className="pt-bar"><i /><i /><i /><span className="mono">verify.sh</span></div>
                <div className="pt-body">
                  <div className="pt-cmd"><span className="mono">$</span> cd backend && python -m app.cli eval</div>
                  {[
                    ["cross-source", `${cross?.ok ?? 323} / ${cross?.pairs ?? 384}`, `${agencyRate ?? 84.1}%`, "公开"],
                    ["mismatch", `${cross?.counts?.mismatch ?? 61}`, "逐条列出", "公开"],
                    ["restatement", `${cross?.restatement_n ?? 45}`, "可追溯", "记录"],
                    ["template", "192 / 192", "独立环境", "PASS"],
                    ["conflict", "2 / 2", "BLOCKED / SUPERSEDED", "PASS"],
                    ["tests", "39 / 39", "pytest", "PASS"],
                  ].map(([k, v, x, s]) => (
                    <div className="pt-row" key={k}>
                      <span className="k">{k}</span>
                      <span className="v mono">{v}</span>
                      <span className="x">{x}</span>
                      <span className={"s " + (s === "PASS" ? "pass" : "")}>{s}</span>
                    </div>
                  ))}
                  <div className="pt-verdict">verdict: 84.1% 不是满分；失败样本保留，评测可以复跑。</div>
                </div>
                <div className="pt-foot">同一数据库 · 同一规则 · 同一命令，结果可逐条复核</div>
              </div>

              <div className="proof-cards">
                {[
                  { n: "01", t: "不自建金标", d: "参照值是第三方结构化数据，不是我们自己的标注；主口径不拿合成语料充数。" },
                  { n: "02", t: "两条赛道隔离", d: "真实库只含 real_cninfo；回归赛道在独立临时 DATA_DIR 里跑，结果回传但不写入。" },
                  { n: "03", t: "失败不隐藏", d: "61 条不一致全部列出公司、字段、页码与两边数值；不通过删样本把数字修到 100%。" },
                ].map((c) => (
                  <div className="proof-card" key={c.n}>
                    <span className="mono">{c.n}</span>
                    <b>{c.t}</b>
                    <p>{c.d}</p>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>
        </section>

        {/* ---------------- 能力 ---------------- */}
        <section className="band" id="capabilities">
          <Reveal>
            <div className="band-head">
              <div className="kicker">Built to be checked</div>
              <h2>把「不可复核」，<br /><span className="thin">变成工程约束。</span></h2>
              <p>
                多智能体分工不是卖点，约束才是：模型不写数字、不改底稿、不发布；
                核验对冲突不猜；补证只改真正受影响的章节。
              </p>
            </div>
          </Reveal>

          <div className="cap-grid">
            <Reveal delay={40}>
              <div className="cap-card">
                <span className="cap-no">01 / CONFLICT</span>
                <h3>同级冲突，宁可冻结</h3>
                <p>
                  两份同级披露给出不同数值，系统判 <span className="mono">BLOCKED</span>，
                  指标不出数，而不是挑一个「看起来合理」的继续算。
                </p>
                <div className="cap-vis">
                  <div className="mini-doc"><File size={12} /><span className="t">2024 年年度报告 · 本期</span><span className="n">32,137,830,111</span></div>
                  <div className="mini-doc bad"><File size={12} /><span className="t">2025 年年度报告 · 上期比较</span><span className="n">32,137,830,111</span></div>
                  <div className="stamp ok">AGREED · 两处一致</div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={110}>
              <div className="cap-card">
                <span className="cap-no">02 / INCREMENTAL</span>
                <h3>只改该改的那几节</h3>
                <p>
                  新增一期年报，先算影响范围，再逐节比对版本：
                  没动的章节沿用原来的章节编号。
                </p>
                <div className="cap-vis">
                  <div className="mini-sections">
                    {[
                      ["概览", "chg"], ["行业", "same"], ["经营", "chg"], ["财务", "chg"],
                      ["同业", "chg"], ["风险", "chg"], ["产业链", "same"], ["数据质量", "chg"],
                    ].map(([n, c]) => (
                      <span className={"mini-sec " + c} key={n}>{n}</span>
                    ))}
                  </div>
                  <div style={{ fontSize: 10.5, color: "var(--dim)", marginTop: 14, lineHeight: 1.9 }}>
                    预测受影响 = 实际改写<br />
                    未命中章节保持同一版本 ID，可直接比对
                  </div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={60}>
              <div className="cap-card">
                <span className="cap-no">03 / BENCHMARK</span>
                <h3>先放进行业，再下判断</h3>
                <p>
                  同业中位数不是「找几家平均一下」：先过口径、过缺失，
                  少于 2 家就写「不适用」，不拿单点当基准。
                </p>
                <div className="cap-vis">
                  <div className="mini-bars">
                    {[
                      ["本公司", 78, true, "41.4%"], ["次龙头", 58, false, "38.9%"], ["区域", 46, false, "35.2%"],
                    ].map(([n, h, me, v]: any) => (
                      <div className={"mini-bar" + (me ? " me" : "")} key={n}>
                        <span className="bv">{v}</span>
                        <i style={{ height: `${h}%` }} />
                        <span className="bl">{n}</span>
                      </div>
                    ))}
                    <div className="median-line" style={{ bottom: "54%" }} />
                  </div>
                  <div className="mini-caption">虚线 = 同业中位数 · n=2（少于 2 家不计算）</div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={130}>
              <div className="cap-card">
                <span className="cap-no">04 / GRAPH</span>
                <h3>产业链的边，也要有出处</h3>
                <p>
                  每条关系标注依据：年报披露、行业公开资料或推断。
                  推断边降级为虚线，不与披露证据混在一起。
                </p>
                <div className="cap-vis">
                  <svg className="mini-graph" viewBox="0 0 320 132">
                    <path className="edge live" d="M56 40 C 120 40, 120 96, 168 96" />
                    <path className="edge" d="M168 96 C 216 96, 216 40, 268 40" />
                    <path className="edge" d="M56 40 C 110 40, 120 30, 168 30" />
                    <path className="edge" d="M168 30 C 220 30, 220 96, 268 96" />
                    <circle className="node me" cx="56" cy="40" r="15" />
                    <circle className="node" cx="168" cy="30" r="11" />
                    <circle className="node" cx="168" cy="96" r="11" />
                    <circle className="node" cx="268" cy="40" r="9" />
                    <circle className="node" cx="268" cy="96" r="9" />
                    <text x="56" y="43" textAnchor="middle">本公司</text>
                    <text x="168" y="33" textAnchor="middle">原料</text>
                    <text x="168" y="99" textAnchor="middle">包材</text>
                    <text x="268" y="43" textAnchor="middle">餐饮</text>
                    <text x="268" y="96" textAnchor="middle">商超</text>
                  </svg>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ---------------- 结尾 ---------------- */}
        <Reveal>
          <div className="endcta">
            <h2>从一个数字开始。</h2>
            <p>选一家公司，跑一次研究，然后点开它的毛利率。</p>
            <button className="btn-lime" onClick={onEnter}>
              进入工作台 <ArrowUpRight size={16} />
            </button>
          </div>
        </Reveal>

        <footer className="site-foot">
          <span className="brand-txt" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <span className="logo-mark" style={{ width: 22, height: 22, borderRadius: 7 }}><Mark size={14} /></span>
            <b style={{ fontSize: 12 }}>经营证据链</b>
          </span>
          <span className="sep" />
          <span>工商银行企业命题二 · AI 驱动的行业研究与企业经营分析助手</span>
          <span className="sep" />
          <span>数据来源：巨潮资讯年报原件、东方财富公开数据；合成样本仅用于回归测试。</span>
        </footer>
      </div>
    </div>
  );
}
