import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const KIND_LABEL: Record<string, string> = {
  metric: "指标复算",
  fact: "原表单元格",
  document: "原件页",
  risk: "规则",
  edge: "产业链边",
  claim: "结论",
};

const STEPS = [
  { key: "caliber", label: "口径", hint: "合并 / 期间 / 单位" },
  { key: "formula", label: "算式", hint: "公式与代值" },
  { key: "cell", label: "单元格", hint: "原页上的那一格" },
  { key: "source", label: "原件", hint: "披露日与校验码" },
] as const;

const UNIT_LABEL: Record<string, string> = {
  fraction: "比率",
  ratio: "比率",
  days: "天",
  "元→元": "元",
  CNY: "元",
};

const BASIS_KEY: Record<string, string> = {
  实体: "研究主体", 财年: "财年", 比较范围: "比较范围", 置信度: "可信度",
  审计层级: "数据来源", 基数版本: "数据版本", 精度步长: "最小精度",
  抽取方式: "读取方式", 置信度提示: "可信度提示", 核验决策: "核验结论",
  版本: "版本", 阈值: "关注阈值", 口径: "口径",
};

const BASIS_VALUE: Record<string, string> = {
  HIGH: "高", MEDIUM: "中", LOW: "低",
  ACCEPTED: "采用", ACCEPTED_WITH_CONFLICT: "有冲突", SUPERSEDED: "已被更正替代",
  AGREED: "已核验", BLOCKED: "阻断", FROZEN: "冻结", MISSING: "缺失",
  primary_table: "主表", summary_table: "摘要表", segment_table: "分部表", narrative: "文字说明",
  parent_table: "母公司表",
  original: "原始披露", restated: "重述", unknown: "未标注", consolidated: "合并",
  total: "整体", segment: "分部", CNY: "人民币",
  table_cell: "表格单元格", text_parse: "文字识别", manual_candidate: "人工候选",
  line_anchor: "年报行定位", cell_anchor: "表格单元格定位",
  annual_report: "年度报告", annual_summary: "年报摘要", correction: "更正公告",
  industry_stats: "行业统计", policy: "政策文件", market_note: "市场资料", quarterly: "季度报告",
  primary: "一手", secondary: "二手",
};

const BASIS_HIDE = new Set(["定义版本", "基数版本", "业务范围"]);

const basisValue = (v: unknown) => BASIS_VALUE[String(v)] || String(v);
const basisKey = (k: string) => BASIS_KEY[k] || k;

const SLOT_LABEL: Record<string, string> = {
  revenue: "营业收入", operating_cost: "营业成本", net_profit_total: "净利润",
  net_profit_parent: "归母净利润", total_assets: "资产总计", total_liabilities: "负债合计",
  total_equity: "所有者权益", operating_cashflow: "经营现金流",
  receivables: "应收账款", inventories: "存货", cur: "本期", prev: "上期",
  revenue_prev: "上年营业收入",
};

const PATH_LABEL: Record<string, string> = {
  income_statement: "利润表", balance_sheet: "资产负债表", cash_flow: "现金流量表",
  segment: "分部信息", summary: "主要会计数据", industry: "行业统计",
  consolidated: "合并口径", parent: "母公司口径", unknown: "口径未标注",
};

const friendlyPath = (p?: string | null) =>
  (p || "").split(" / ").map((x) => PATH_LABEL[x.trim()] || x).join(" · ");

const cellLabel = (id?: string | null) => {
  const m = /^r(\d+)c(\d+)$/i.exec(id || "");
  return m ? `第 ${m[1]} 行 · 第 ${m[2]} 列` : "原表单元格";
};

const unitLabel = (u: string | undefined) => {
  if (!u) return "";
  return UNIT_LABEL[u] || u;
};

type StepKey = (typeof STEPS)[number]["key"];

export default function EvidenceDrawer({ refId, onClose, onJump }: { refId: string; onClose: () => void; onJump?: (r: string) => void }) {
  const [ev, setEv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [auto, setAuto] = useState(true);
  const [run, setRun] = useState(0);
  const [full, setFull] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const autoRef = useRef(true);

  useEffect(() => {
    setEv(null);
    setErr(null);
    setStep(0);
    setFull(false);
    api.evidence(refId).then(setEv).catch((e) => setErr(String(e.message || e)));
  }, [refId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    autoRef.current = auto;
  }, [auto]);

  // 打开即演示：每 900ms 点亮一层，做成可暂停的四步核对。
  useEffect(() => {
    if (!ev) return;
    setStep(0);
    setAuto(true);
    autoRef.current = true;
    let n = 0;
    const boot = window.setTimeout(() => {
      if (autoRef.current) setStep(1);
    }, 500);
    const timer = window.setInterval(() => {
      if (!autoRef.current) {
        window.clearInterval(timer);
        return;
      }
      n += 1;
      setStep((s) => Math.min(5, s + 1));
      if (n >= 4) window.clearInterval(timer);
    }, 900);
    return () => {
      window.clearTimeout(boot);
      window.clearInterval(timer);
    };
  }, [ev, refId, run]);

  // 当前层推进时，抽屉内部把该层顶端带到固定链下方；不滚动背后的报告页。
  useEffect(() => {
    if (!ev || step < 1 || step > 4) return;
    const body = bodyRef.current;
    const el = document.getElementById(`evc-layer-${step}`);
    if (!body || !el) return;
    const br = body.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    const top = er.top - br.top + body.scrollTop - 76;
    body.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }, [step, ev]);

  const goto = (n: number) => {
    setAuto(false);
    autoRef.current = false;
    setStep(n);
  };

  const replay = () => {
    setStep(0);
    setAuto(true);
    autoRef.current = true;
    setRun((r) => r + 1);
  };

  const bbox = ev?.location?.bbox;
  const pageUrl = ev?.document?.document_id
    ? `/api/documents/${encodeURIComponent(ev.document.document_id)}/page/${ev.location?.page}.png`
    : null;
  const has: Record<StepKey, boolean> = {
    caliber: !!(ev?.value_display || Object.keys(ev?.basis || {}).length),
    formula: !!ev?.formula?.text,
    cell: !!(ev?.document && ev?.location),
    source: !!ev?.document,
  };
  const bboxArr = Array.isArray(bbox) ? bbox : null;
  const layerClass = (n: number) =>
    "layer evc-layer" + (step >= n ? " lit" : "") + (step === n ? " now" : "");
  const layerState = (n: number) => (step > n ? "已核" : step === n ? "核对中" : "待核对");

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-h">
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
              <span className="pill" style={{ color: "var(--ev)", borderColor: "rgba(255,206,106,.35)" }}>
                {KIND_LABEL[ev?.kind] || "引用"}
              </span>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--dim)" }}>可逐层核对</span>
            </div>
            <h3>{ev?.title || "正在打开证据…"}</h3>
            {ev?.location?.heading_path && (
              <div className="mono" style={{ fontSize: 9.5, color: "var(--dim)", marginTop: 4 }}>
                {friendlyPath(ev.location.heading_path)}
              </div>
            )}
          </div>
          <button className="drawer-close" onClick={onClose}>关闭 ESC</button>
        </div>

        <div
          className="drawer-b"
          ref={bodyRef}
          onWheel={() => setAuto(false)}
          onTouchStart={() => setAuto(false)}
        >
          {ev && (
            <div className="evc-chain">
              <div className="evc-chain-top">
                <span className="evc-chain-title"><i className="evc-mark" />四层证据链</span>
                <span className={"evc-chain-now" + (step >= 5 ? " done" : "")}>
                  {step === 0 ? "准备定位" : step >= 5 ? "核对完成 · 可回到阅读" : step === 4 ? "最后一层 · 原件" : `第 ${step} / 4 层 · ${STEPS[step - 1].label}`}
                </span>
                <button className="evc-replay" onClick={replay} title="重播四层点亮">
                  <span>↻</span> 重播
                </button>
              </div>
              <div
                className="evc-track"
                style={{ ["--evc-p" as any]: `${step <= 1 ? 0 : Math.min(100, ((step - 1) / 3) * 100)}%` }}
              >
                <span className="evc-line" />
                <span className="evc-fill" />
                {STEPS.map((s, i) => {
                  const n = i + 1;
                  const done = step > n;
                  const now = step === n;
                  return (
                    <button
                      key={s.key}
                      className={"evc-node" + (step >= n ? " on" : "") + (now ? " now" : "") + (has[s.key] ? "" : " na")}
                      onClick={() => goto(n)}
                      aria-current={now ? "step" : undefined}
                      title={`${s.label}：${s.hint}`}
                    >
                      <span className="evc-dot">{done ? "✓" : n}</span>
                      <span className="evc-l">{s.label}</span>
                      <span className="evc-s">{has[s.key] ? (done ? "已核" : now ? "核对中" : "待核对") : "不适用"}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {err && <div className="empty">{err}</div>}
          {!ev && !err && <div className="empty">正在打开证据…</div>}

          {ev && (
            <>
              {/* ① 口径 */}
              <section className={layerClass(1)} id="evc-layer-1">
                <div className="lh">
                  <b>① 口径</b><span>先看值，再看合并范围、期间和单位</span>
                  <span className="evc-ls">{layerState(1)}</span>
                </div>
                <div className="lb">
                  {ev.value_display ? (
                    <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                      <span className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{ev.value_display}</span>
                      <span className="sub">{unitLabel(ev.unit)}</span>
                    </div>
                  ) : (
                    <div className="evc-void">这是原页片段引用，没有独立的指标值；口径信息见下方标签。</div>
                  )}
                  <div className="chips" style={{ marginTop: 10 }}>
                    {Object.entries(ev.basis || {}).filter(([k]) => !BASIS_HIDE.has(k)).map(([k, v]) => (
                      <span className="chip" key={k} style={{ cursor: "default" }}>
                        <span style={{ color: "var(--dim)" }}>{basisKey(k)}</span>
                        <span style={{ color: "var(--text)" }}>{basisValue(v)}</span>
                      </span>
                    ))}
                  </div>
                </div>
              </section>

              {/* ② 算式 */}
              <section className={layerClass(2)} id="evc-layer-2">
                <div className="lh">
                  <b>② 算式</b>
                  <span>{ev.formula?.text ? "按公式逐项复算　点变量可继续下钻" : "原表事实不需要公式"}</span>
                  <span className="evc-ls">{layerState(2)}</span>
                </div>
                <div className="lb">
                  {ev.formula?.text ? (
                    <>
                      <div className="quote" style={{ marginBottom: 10 }}>{ev.formula.text}</div>
                      {ev.formula.description && <div className="sub" style={{ marginBottom: 8 }}>{ev.formula.description}</div>}
                      {ev.formula.inputs?.length > 0 && (
                        <div className="tw">
                          <table className="tb">
                            <thead>
                              <tr><th>变量</th><th>取值</th><th>页码</th><th>来源文档</th></tr>
                            </thead>
                            <tbody>
                              {ev.formula.inputs.map((i: any, n: number) => (
                                <tr key={n}>
                                  <td
                                    className="lab"
                                    style={{ cursor: i.ref ? "pointer" : "default", color: i.ref ? "var(--ev)" : undefined }}
                                    onClick={() => i.ref && onJump && onJump(i.ref)}
                                  >
                                    {SLOT_LABEL[i.slot] || "输入项"}
                                  </td>
                                  <td>{i.display}</td>
                                  <td>{i.page ? `P${i.page} · ${cellLabel(i.cell_id)}` : "—"}</td>
                                  <td style={{ fontFamily: "inherit", fontSize: 11, textAlign: "left" }}>{i.document || "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {ev.formula.raw_value && (
                        <div className="mono" style={{ fontSize: 12, marginTop: 10, color: "var(--ev)" }}>
                          换算：{ev.formula.raw_value} × {ev.formula.unit_scale} ={" "}
                          {Number(ev.formula.value_text).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                        </div>
                      )}
                      {ev.formula.status && ev.formula.status !== "OK" && (
                        <div className="note">状态 {ev.formula.status}：{ev.formula.missing_reason || "指标未产出数值"}</div>
                      )}
                    </>
                  ) : (
                    <div className="evc-void">这条引用直接落到原表单元格，不需要公式复算。下一层看它具体在哪一格。</div>
                  )}
                </div>
              </section>

              {/* ③ 单元格 */}
              <section className={layerClass(3)} id="evc-layer-3">
                <div className="lh">
                  <b>③ 单元格</b>
                  <span>{friendlyPath(ev.location?.heading_path)} {ev.location?.cell_id ? `· ${cellLabel(ev.location.cell_id)}` : ""}</span>
                  <span className="evc-ls">{layerState(3)}</span>
                </div>
                <div className="lb">
                  {pageUrl && ev.location?.page ? (
                    <>
                      <div className={"evc-crop" + (full ? " full" : "")}>
                        <div
                          className="evc-pan"
                          style={full || !bboxArr || bboxArr[1] <= 0.52 ? undefined : { transform: `translateY(calc(390px - ${(bboxArr[1] * 100).toFixed(2)}%))` }}
                        >
                          <img src={pageUrl} alt="原页" />
                          {bboxArr && (
                            <div
                              className={"hl" + (bboxArr[0] > 0.55 ? " hl-r" : "")}
                              data-label={`${ev.location.row_label || ""} ${cellLabel(ev.location.cell_id)}`}
                              style={{
                                left: `${bboxArr[0] * 100}%`,
                                top: `${bboxArr[1] * 100}%`,
                                width: `${(bboxArr[2] - bboxArr[0]) * 100}%`,
                                height: `${(bboxArr[3] - bboxArr[1]) * 100}%`,
                              }}
                            />
                          )}
                        </div>
                      </div>
                      <div className="hstack" style={{ marginTop: 8 }}>
                        <button className="btn ghost sm" onClick={() => setFull((v) => !v)}>
                          {full ? "收起页面" : "查看整页"}
                        </button>
                        <span className="sub">红框即抽取位置；不在主表时，先看表名与列头。</span>
                      </div>
                    </>
                  ) : (
                    <div className="evc-void">该引用是结论或规则，没有可定位的单元格。</div>
                  )}
                  {ev.excerpt && <div className="quote" style={{ marginTop: 10 }}>{ev.excerpt}</div>}
                </div>
              </section>

              {/* ④ 原件 */}
              <section className={layerClass(4)} id="evc-layer-4">
                <div className="lh">
                  <b>④ 原件</b><span>披露日与校验码共同标识这份原件</span>
                  <span className="evc-ls">{layerState(4)}</span>
                </div>
                <div className="lb">
                  {ev.document ? (
                    <>
                      <div className="basis">
                        <span className="k">标题</span><span className="v">{ev.document.title}</span>
                        <span className="k">发布主体</span><span className="v">{ev.document.issuer_name || ev.document.issuer}</span>
                        <span className="k">类型</span><span className="v">{basisValue(ev.document.source_type)} · {basisValue(ev.document.tier)}</span>
                        <span className="k">披露日</span><span className="v mono">{ev.document.published_on || "未标注"}</span>
                        <span className="k">入库日</span><span className="v mono">{ev.document.retrieved_at ? String(ev.document.retrieved_at).slice(0, 10) : "—"}</span>
                        <span className="k">原件校验码</span><span className="v mono" style={{ fontSize: 10.5 }} title={ev.document.sha256}>{String(ev.document.sha256).slice(0, 24)}…</span>
                        <span className="k">读取方式</span><span className="v">PDF 表格识别</span>
                      </div>
                      <div className="hstack" style={{ marginTop: 10 }}>
                        <a className="btn ghost" href={`/api/documents/${encodeURIComponent(ev.document.document_id)}/file`} target="_blank" rel="noreferrer">打开原件 PDF</a>
                      </div>
                    </>
                  ) : (
                    <div className="evc-void">该引用没有绑定原件。</div>
                  )}
                </div>
              </section>

              {ev.reasons?.filter(Boolean).length > 0 && (
                <div className="evc-notes">
                  <div className="evc-notes-h"><b>采信理由</b><span>逐条记录，不是事后措辞</span></div>
                  {ev.reasons.filter(Boolean).map((r: string, i: number) => (
                    <div key={i}>· {r}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
