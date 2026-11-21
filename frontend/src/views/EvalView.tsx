import { useEffect, useState } from "react";
import { api } from "../api";
import { ArrowUpRight, Check, File, Shield } from "../components/icons";

const pct = (v: number | undefined | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

const FIELD_LABEL: Record<string, string> = {
  revenue: "营业收入", operating_cost: "营业成本", net_profit_parent: "归母净利润",
  total_assets: "资产总计", total_liabilities: "负债合计", total_equity: "所有者权益",
  operating_cashflow: "经营现金流", inventories: "存货", receivables: "应收账款",
};
const DATASET_LABEL: Record<string, string> = {
  real_cninfo: "真实年报",
  synthetic_regression: "合成回归",
  demo_controlled: "演练材料",
};
const STATUS_LABEL: Record<string, string> = {
  OK: "有效", MISSING_INPUT: "缺证", INVALID_BASE: "不可比",
};
const TEST_STATUS_LABEL: Record<string, string> = {
  exact: "一致", rounding: "舍入", unit: "单位错", mismatch: "不一致",
};

function Bar({ v, tone = "var(--accent)" }: { v: number; tone?: string }) {
  return (
    <span className="ev-bar">
      <i style={{ width: `${Math.max(2, Math.min(100, v * 100))}%`, background: tone }} />
    </span>
  );
}

function Gauge({ value }: { value: number }) {
  const r = 62;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <svg viewBox="0 0 160 160" className="gauge">
      <circle cx="80" cy="80" r={r} className="gauge-track" />
      <circle
        cx="80" cy="80" r={r} className="gauge-arc"
        strokeDasharray={c} strokeDashoffset={c * (1 - v)}
        transform="rotate(-90 80 80)"
      />
      <text x="80" y="74" textAnchor="middle" className="gauge-v">{(v * 100).toFixed(1)}<tspan className="gauge-p">%</tspan></text>
      <text x="80" y="94" textAnchor="middle" className="gauge-l">跨源一致率</text>
    </svg>
  );
}

const TRACK_META: Record<string, { name: string; desc: string; tag: string }> = {
  cross_source: { name: "跨源互证", desc: "巨潮年报原件 vs 第三方结构化数据", tag: "主口径" },
  template_regression: { name: "模板语料回归", desc: "合成 PDF 的逐格对照标准，用于检查读取是否退化", tag: "回归" },
  conflict_injection: { name: "冲突判别", desc: "未公告重述应冻结；正式更正应替代", tag: "回归" },
  incremental: { name: "增量隔离", desc: "补证只改命中章节，未命中章节保持原版本", tag: "回归" },
};

export default function EvalView({ onRef }: { onRef: (r: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [fieldFilter, setFieldFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const load = () => {
    setBusy(true);
    api.eval().then(setData).finally(() => setBusy(false));
  };

  useEffect(load, []);

  if (!data) return <div className="empty">评测运行中…（首次需要扫描 384 对跨源事实）</div>;
  if (data.detail) return <div className="empty">{String(data.detail)}</div>;

  const x = data.cross_source || {};
  const c = data.citations || {};
  const r = data.recompute || {};
  const counts = x.counts || {};
  const coverage = x.coverage || {};
  const taxonomy = x.failure_taxonomy || [];
  const tracks = data.tracks || {};
  const byField = Object.entries(x.by_field || {}) as [string, any][];
  const byInd = Object.entries(x.by_industry || {}) as [string, any][];

  const failures = (x.failures || []).filter((f: any) =>
    (fieldFilter === "all" || f.field === fieldFilter) &&
    (statusFilter === "all" || f.status === statusFilter));

  const story = pickStory(x.failures || []);

  const fieldOptions = [...new Set((x.failures || []).map((f: any) => f.field))];

  return (
    <div className="view-enter eval2">
      <div className="page-head eval-head">
        <div>
          <div className="kicker">Verification console</div>
          <h2>可验证性控制台</h2>
          <p className="sub">
            主口径不自己造标准答案：一边是巨潮年报原件的读取结果，一边是第三方结构化数据，逐项对照。
            失败样本全部公开，不通过删样本把数字修到 100%。
          </p>
        </div>
        <div className="spacer" />
        <span className="badge-mode">数据集 <b>{DATASET_LABEL[x.dataset_tag] || "真实年报"}</b></span>
        <button className="btn sm" onClick={load} disabled={busy}>{busy ? "重跑中…" : "重新运行"}</button>
      </div>

      <div className="eval-hero">
        <div className="panel gauge-panel">
          <Gauge value={x.agreement || 0} />
          <div className="gauge-side">
            <div><b className="mono">{x.ok}</b><span>一致 / {x.pairs} 可比</span></div>
            <div><b className="mono">{counts.mismatch ?? 0}</b><span>真不一致（逐条列出）</span></div>
            <div><b className="mono">{x.restatement_n ?? 0}</b><span>跨年重述记录</span></div>
          </div>
        </div>
        <div className="eval-cells">
          <div className="eval-cell big">
            <span className="ev-n">{x.pairs ?? "—"}</span>
            <span className="ev-l">可比值</span>
            <span className="ev-x">{coverage.companies || x.companies} 家公司 · {x.industries} 行业 · 9 字段 × 3 财年</span>
          </div>
          <div className="eval-cell">
            <span className="ev-n">{coverage.compared ?? "—"}</span>
            <span className="ev-l">进入分母</span>
            <span className="ev-x">PDF 与第三方都有值才计；覆盖率 {pct(coverage.field_coverage)}</span>
          </div>
          <div className="eval-cell">
            <span className="ev-n">{pct(c.rate)}</span>
            <span className="ev-l">引用可达</span>
            <span className="ev-x">{c.reachable} / {c.refs} 条引用能打开文档、公式或定位</span>
          </div>
          <div className="eval-cell">
            <span className="ev-n">{r.metrics ? `${r.consistent}/${r.metrics}` : "—"}</span>
            <span className="ev-l">内部复算</span>
            <span className="ev-x">另写一套公式重算；内部一致性，不是外部准确率</span>
          </div>
        </div>
      </div>

      <FailureStory f={story} total={counts.mismatch ?? 0} onRef={onRef} />

      <div className="track-grid">
        {Object.entries(TRACK_META).map(([key, meta]) => {
          const t = tracks[key] || {};
          const ok = t.status === "ok";
          const detail = key === "template_regression"
            ? (data.extraction?.gold ? `${data.extraction.hit} / ${data.extraction.gold} 逐格命中` : null)
            : key === "conflict_injection"
              ? (data.conflicts?.total ? `${data.conflicts.pass} / ${data.conflicts.total} 用例通过` : null)
              : key === "incremental"
                ? (data.incremental?.pass != null ? (data.incremental.pass ? "影响面一致 · 未命中章节版本不变" : "影响面不一致") : null)
                : `${x.pairs} 对 · ${pct(x.agreement)}`;
          return (
            <div className={"track-card" + (ok ? " ok" : " na")} key={key}>
              <div className="tc-top">
                <span className={"pill " + (ok ? "HIGH" : "WARN")}>{ok ? "已运行" : "未运行"}</span>
                {t.isolated && <span className="tc-iso">独立环境</span>}
                <span className="tc-tag">{meta.tag}</span>
              </div>
              <b>{meta.name}</b>
              <span>{meta.desc}</span>
              {detail && <span className="tc-detail mono">{detail}</span>}
              <em className="mono">数据集：{DATASET_LABEL[t.dataset_tag] || "—"}</em>
              {!ok && <div className="tc-note">当前没有可用的回归样本；回归测试只在独立环境中运行。</div>}
            </div>
          );
        })}
      </div>
      <div className="eval-note" style={{ marginTop: -4, marginBottom: 14 }}>
        评测分为真实年报核验与回归测试两组；回归测试只用于检查能力是否退化，不作为对外精度表述。
      </div>

      <div className="eval-grid">
        <div className="panel">
          <div className="panel-h"><h3>按字段</h3><span className="hint">一致 = 完全相等或差 ≤1 元</span></div>
          <table className="tb">
            <thead><tr><th>字段</th><th style={{ width: 130 }}>一致率</th><th>命中 / 可比</th><th>原件缺</th></tr></thead>
            <tbody>
              {byField.map(([k, v]) => (
                <tr key={k}>
                  <td className="lab">{FIELD_LABEL[k] || k}</td>
                  <td><Bar v={v.rate} tone={v.rate >= 0.85 ? "var(--accent)" : v.rate >= 0.7 ? "var(--warn)" : "var(--danger)"} /></td>
                  <td className="mono">{v.ok} / {v.compared}</td>
                  <td className="mono" style={{ color: "var(--dim)" }}>{v.miss_pdf}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="note">「原件缺」= 该字段没有从 PDF 抽到，不计入分母；覆盖率也是结论的一部分。</div>
        </div>

        <div className="panel">
          <div className="panel-h"><h3>按行业</h3><span className="hint">同一套规则，不按结果调参</span></div>
          {byInd.map(([k, v]) => (
            <div className="ev-row" key={k}>
              <span className="l">{v.name || k}</span>
              <Bar v={v.rate} tone={v.rate >= 0.85 ? "var(--accent)" : v.rate >= 0.7 ? "var(--warn)" : "var(--danger)"} />
              <span className="v mono">{pct(v.rate)}</span>
              <span className="n mono">{v.ok}/{v.compared}</span>
            </div>
          ))}
          <div className="doc-types">
            {Object.entries(coverage.by_type || {}).map(([k, n]) => (
              <span className="dt" key={k}><File size={10} />{k} <b>{n as number}</b></span>
            ))}
          </div>
          <div className="note">
            比对规则固定：完全相等记一致；相差 1 元内记舍入；整千/整万倍记单位错；其余记不一致。
          </div>
        </div>
      </div>

      <div className="tax-grid">
        {taxonomy.map((t: any) => (
          <div className={"tax-card " + t.key} key={t.key}>
            <div className="tax-n">{t.count}</div>
            <b>{t.label}</b>
            <span>{t.hint}</span>
            <div className="tax-fields">
              {(t.fields || []).map((f: any) => <i key={f.label}>{f.label} ×{f.count}</i>)}
            </div>
          </div>
        ))}
        <div className="tax-card unit-less">
          <div className="tax-n">{counts.rounding ?? 0}</div>
          <b>舍入相容</b>
          <span>差值落在单位/精度容差内，不计为不一致</span>
          <div className="tax-fields"><i>不进入失败样本</i></div>
        </div>
      </div>

      <div className="panel" id="fail-samples" style={{ marginTop: 16 }}>
        <div className="panel-h">
          <h3>不一致样本</h3>
          <span className="hint">按真实结果列出，不做删改</span>
          <span className="spacer" />
          <div className="filter-row">
            <button className={fieldFilter === "all" ? "on" : ""} onClick={() => setFieldFilter("all")}>全部字段</button>
            {fieldOptions.map((f: any) => (
              <button key={f} className={fieldFilter === f ? "on" : ""} onClick={() => setFieldFilter(f)}>{FIELD_LABEL[f] || f}</button>
            ))}
            <span className="sep" />
            {["all", "mismatch", "unit"].map((s) => (
              <button key={s} className={statusFilter === s ? "on" : ""} onClick={() => setStatusFilter(s)}>
                {s === "all" ? "全部类型" : TEST_STATUS_LABEL[s]}
              </button>
            ))}
          </div>
        </div>
        <div className="tw">
          <table className="tb">
            <thead>
              <tr><th>公司</th><th>字段</th><th>财年</th><th>原件抽取</th><th>第三方</th><th>差额</th><th>类型</th><th>页码</th><th>证据</th></tr>
            </thead>
            <tbody>
              {failures.map((f: any, i: number) => (
                <tr key={i}>
                  <td className="lab">{f.name}</td>
                  <td>{FIELD_LABEL[f.field] || f.label}</td>
                  <td className="mono">{f.year}</td>
                  <td className="mono">{fmt(f.pdf)}</td>
                  <td className="mono">{fmt(f.ref)}</td>
                  <td className="mono" style={{ color: "var(--danger)" }}>{fmt(f.diff)}</td>
                  <td><span className={"pill " + (f.status === "unit" ? "WARN" : "BLOCKED")}>{TEST_STATUS_LABEL[f.status] || "不一致"}</span></td>
                  <td className="mono" style={{ color: "var(--dim)" }}>P{f.page}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {f.fact_id ? (
                      <button className="btn ghost sm" style={{ padding: "2px 7px" }} onClick={() => onRef(f.fact_id)}>查看</button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
              {failures.length === 0 && <tr><td colSpan={9} className="empty">当前筛选下没有样本</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="note">
          当前只列前 24 条失败样本，完整集合为 {counts.mismatch ?? 0} 条不一致
          {(counts.unit ?? 0) > 0 ? ` + ${counts.unit} 条单位错` : ""}；评测可复跑。
        </div>
      </div>

      {(x.restatements || []).length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-h">
            <h3>跨年重述</h3>
            <span className="hint">同一指标在两份年报里数值不同，说明比较数被重述</span>
          </div>
          <div className="tw">
            <table className="tb">
              <thead><tr><th>公司</th><th>字段</th><th>财年</th><th>出现的数值</th><th>来源</th></tr></thead>
              <tbody>
                {x.restatements.map((s: any, i: number) => (
                  <tr key={i}>
                    <td className="lab">{s.name}</td>
                    <td>{FIELD_LABEL[s.field] || s.field}</td>
                    <td className="mono">{s.year}</td>
                    <td className="mono">{s.values.map((v: string) => fmt(v)).join(" / ")}</td>
                    <td style={{ fontSize: 10.5, color: "var(--dim)" }}>{s.docs.join("；")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="eval-foot">
        <div><Shield size={13} /><b>不做的评测</b><span>不把「跑通率」当准确率；不建自造金标；不因样本少而宣称高精度。</span></div>
        <div><Check size={13} /><b>可以复跑</b><span>同一数据库、同一规则、同一命令，结果可逐条复核。</span></div>
        <div><ArrowUpRight size={13} /><b>失败归因</b><span>差异只按量级归类，不断言根因；根因需回原页人工确认。</span></div>
      </div>
    </div>
  );
}

const STORY_NOTES: Record<string, { title: string; cause: string; pageLabel: string }> = {
  "SH:600132|operating_cashflow|2023": {
    title: "一条 31.5 亿的差额，带我们回到第 97 页",
    cause: "第 97 页是「母公司现金流量表」的 2023 年列；同为「经营活动产生的现金流量净额」这一行，原件是 -54,748,707.69，读取结果却把这一页误记为合并口径。第三方是合并口径 30.97 亿，跨源核对因此判为不一致。回原页确认：更像选错表，而不是抄错数。",
    pageLabel: "P97 · 母公司现金流量表",
  },
};

function pickStory(failures: any[]) {
  const pinned = failures.find(
    (f) => f.entity_id === "SH:600132" && f.field === "operating_cashflow" && Number(f.year) === 2023,
  );
  if (pinned) return pinned;
  return [...failures].sort((a, b) => Math.abs(Number(b.diff)) - Math.abs(Number(a.diff)))[0] || null;
}

function parseBBox(v: any): number[] | null {
  try {
    const b = typeof v === "string" ? JSON.parse(v) : v;
    if (Array.isArray(b) && b.length === 4) return b.map(Number);
  } catch {
    /* 定位缺失时仍展示故事卡，只是不画红框 */
  }
  return null;
}

function FailureStory({ f, total, onRef }: { f: any; total: number; onRef: (r: string) => void }) {
  if (!f) return null;
  const note = STORY_NOTES[`${f.entity_id}|${f.field}|${f.year}`] || {
    title: "一条失败，如何被定位",
    cause: "先看差额，再回原页核对表头、期间与合并口径。这里只描述现象，根因由人工确认。",
    pageLabel: `P${f.page} · 原页`,
  };
  const bbox = parseBBox(f.bbox);
  const pageUrl = f.doc_id && f.page
    ? `/api/documents/${encodeURIComponent(f.doc_id)}/page/${f.page}.png`
    : null;
  const pdfUrl = f.doc_id
    ? `/api/documents/${encodeURIComponent(f.doc_id)}/file#page=${f.page}`
    : null;
  const raw = (v: any) => {
    const n = Number(v);
    if (!isFinite(n)) return String(v ?? "—");
    return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const zoom = 2.4;
  const clamp = (v: number) => Math.max(0, Math.min(100, v));
  const bgX = bbox ? clamp(((bbox[0] * zoom - 0.5) / (zoom - 1)) * 100) : 50;
  const bgY = bbox ? clamp(((bbox[1] * zoom - 0.5) / (zoom - 1)) * 100) : 50;

  return (
    <div className="fail-story">
      <div className="fs-head">
        <div>
          <div className="fs-kicker">Failure story · 失败样本故事卡</div>
          <h3>{note.title}</h3>
          <p>
            {f.name} · {f.year} 年 · {FIELD_LABEL[f.field] || f.label} · 1 / {total} 条不一致
          </p>
        </div>
        <div className="fs-head-right">
          <span className="fs-status">不一致</span>
          <button
            className="fs-all"
            onClick={() => document.getElementById("fail-samples")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          >
            全部 {total} 条 <ArrowUpRight size={10} />
          </button>
        </div>
      </div>

      <div className="fs-body">
        <div className="fs-left">
          <div className="fs-nums">
            <div className="fs-num">
              <span>原件抽取</span>
              <b className="mono">{raw(f.pdf)}</b>
              <em>{note.pageLabel} · 原表单元格</em>
            </div>
            <div className="fs-neq">≠</div>
            <div className="fs-num ref">
              <span>第三方结构数据</span>
              <b className="mono">{raw(f.ref)}</b>
              <em>合并口径 · FY{f.year}</em>
            </div>
          </div>

          <div className="fs-diff">
            <span>差额</span>
            <b className="mono">{raw(f.diff)}</b>
            <em>完全相等记一致 · 1 元内记舍入 · 其余记不一致</em>
          </div>

          <div className="fs-find">
            <b>回原页</b>
            <p>{note.cause}</p>
          </div>

          <div className="fs-actions">
            <button className="btn sm" onClick={() => onRef(f.fact_id)} disabled={!f.fact_id}>
              打开四层证据 <ArrowUpRight size={10} />
            </button>
            {pageUrl && <a className="btn ghost sm" href={pageUrl} target="_blank" rel="noreferrer">查看原页</a>}
            {pdfUrl && <a className="btn ghost sm" href={pdfUrl} target="_blank" rel="noreferrer">打开原件</a>}
          </div>
        </div>

        <div className="fs-visual">
          <div className="fs-page">
            <div className="fs-page-inner">
              {pageUrl ? <img src={pageUrl} alt={`第 ${f.page} 页`} /> : <div className="fs-page-empty">原页暂不可用</div>}
              {bbox && (
                <span
                  className="fs-hl"
                  style={{
                    left: `${bbox[0] * 100}%`,
                    top: `${bbox[1] * 100}%`,
                    width: `${(bbox[2] - bbox[0]) * 100}%`,
                    height: `${(bbox[3] - bbox[1]) * 100}%`,
                  }}
                />
              )}
            </div>
            <div className="fs-cap mono">{note.pageLabel}</div>
          </div>
          {pageUrl && bbox && (
            <div
              className="fs-zoom"
              style={{
                backgroundImage: `url(${pageUrl})`,
                backgroundSize: `${zoom * 100}% auto`,
                backgroundPosition: `${bgX}% ${bgY}%`,
              }}
            >
              <span>局部放大 · FY{f.year} 列</span>
            </div>
          )}
        </div>
      </div>

      <div className="fs-foot">
        这条失败不会被隐藏：它同时出现在下方逐条表里，可复跑、可回到原页。
      </div>
    </div>
  );
}

function fmt(v: any) {
  const n = Number(v);
  if (!isFinite(n)) return String(v ?? "—");
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(1)} 万`;
  return n.toFixed(0);
}
