import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import Chart from "../components/Chart";
import ChainGraph from "../components/ChainGraph";
import { ArrowUpRight, Play } from "../components/icons";
import { useActiveSection } from "../components/motion";

type Props = {
  data: any;
  onRef: (ref: string) => void;
  subject?: any;
  right?: React.ReactNode;
  onOpenProvenance?: () => void;
};

const nf = (v: any, d = 2) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });

const ORDER = ["overview", "industry", "operations", "financials", "peer", "risk", "chain", "data_quality"];

const CONF_LABEL: Record<string, string> = { HIGH: "高", MEDIUM: "中", LOW: "低" };
const STATUS_LABEL: Record<string, string> = {
  MISSING_INPUT: "缺证", INVALID_BASE: "不可比", OK: "有效",
  TRIGGERED: "已触发", NOT_TRIGGERED: "未触发", NOT_EVALUABLE: "待核",
};
const ISSUE_LABEL: Record<string, string> = {
  SCOPE_MISMATCH: "口径差异", ROUNDING_COMPATIBLE: "舍入相容",
  NUMERIC_CONFLICT: "数值冲突", COVERAGE_GAP: "覆盖缺口",
  SCANNED_UNSUPPORTED: "扫描件未识别", STATEMENT_NOT_FOUND: "报表未定位",
  HEADER_UNRESOLVED: "表头未识别", PAGE_RUN_IGNORED: "跨页未合并",
};

const EV_CACHE = new Map<string, any>();
const EV_PENDING = new Map<string, Promise<any>>();

function loadEvidence(r: string): Promise<any> {
  const hit = EV_CACHE.get(r);
  if (hit) return Promise.resolve(hit);
  const pending = EV_PENDING.get(r);
  if (pending) return pending;
  const p = api
    .evidence(r)
    .then((d) => {
      EV_CACHE.set(r, d);
      return d;
    })
    .finally(() => EV_PENDING.delete(r));
  EV_PENDING.set(r, p);
  return p;
}

type TipState = { data: any | null; loading: boolean; x: number; y: number };

function CiteChip({ r, meta, onRef }: { r: string; meta: any; onRef: (r: string) => void }) {
  const ref = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TipState | null>(null);
  const over = useRef(false);
  const delay = useRef<number | null>(null);
  const linger = useRef<number | null>(null);

  const clearDelay = () => {
    if (delay.current) {
      window.clearTimeout(delay.current);
      delay.current = null;
    }
  };
  const clearLinger = () => {
    if (linger.current) {
      window.clearTimeout(linger.current);
      linger.current = null;
    }
  };

  const anchor = (data: any | null, loading: boolean) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    // 先给一个粗位置，useLayoutEffect 会按真实高度做翻转与夹取，避免溢出视口。
    const below = box.bottom + 10;
    const y = below + 250 > window.innerHeight ? Math.max(10, box.top - 260) : below;
    setTip({ data, loading, x: box.left, y });
  };

  const open = () => {
    over.current = true;
    clearLinger();
    const cached = EV_CACHE.get(r);
    if (cached) {
      clearDelay();
      anchor(cached, false);
      return;
    }
    loadEvidence(r).catch(() => {});
    if (delay.current) return;
    delay.current = window.setTimeout(() => {
      delay.current = null;
      if (over.current) anchor(null, true);
    }, 90);
  };

  const close = () => {
    over.current = false;
    clearDelay();
    clearLinger();
    setTip(null);
  };

  const leaveChip = () => {
    clearDelay();
    clearLinger();
    linger.current = window.setTimeout(() => {
      linger.current = null;
      over.current = false;
      setTip(null);
    }, 170);
  };

  // 数据到达后原地补全，不打断阅读位置。
  useEffect(() => {
    if (!tip?.loading) return;
    let alive = true;
    loadEvidence(r)
      .then((data) => {
        if (alive && over.current) setTip((t) => (t ? { ...t, data, loading: false } : t));
      })
      .catch(() => {
        if (alive) setTip((t) => (t && t.loading ? null : t));
      });
    return () => {
      alive = false;
    };
  }, [tip?.loading, r]);

  // 视口夹取：左右不出界，下方不够就翻到上方。
  useLayoutEffect(() => {
    if (!tip || !tipRef.current || !ref.current) return;
    const chip = ref.current.getBoundingClientRect();
    const box = tipRef.current.getBoundingClientRect();
    const pad = 10;
    const gap = 10;
    let left = chip.left;
    if (left + box.width > window.innerWidth - pad) left = window.innerWidth - pad - box.width;
    left = Math.max(pad, left);
    let top = chip.bottom + gap;
    let side = "bottom";
    if (top + box.height > window.innerHeight - pad) {
      top = Math.max(pad, chip.top - gap - box.height);
      side = "top";
    }
    tipRef.current.style.left = `${left}px`;
    tipRef.current.style.top = `${top}px`;
    tipRef.current.dataset.side = side;
    const caret = Math.max(14, Math.min(chip.left - left + 10, box.width - 24));
    tipRef.current.style.setProperty("--caret-x", `${caret}px`);
  }, [tip]);

  // 滚动、改窗、Esc 都让预览让位，避免浮层与锚点脱节。
  useEffect(() => {
    if (!tip) return;
    const dismiss = () => {
      over.current = false;
      setTip(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    };
    window.addEventListener("scroll", dismiss, true);
    window.addEventListener("resize", dismiss);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", dismiss, true);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("keydown", onKey);
    };
  }, [tip !== null]);

  useEffect(() => () => {
    clearDelay();
    clearLinger();
  }, []);

  const d = tip?.data;
  const doc = d?.document;
  const loc = d?.location;
  const audit = d?.basis
    ? (Object.entries(d.basis).find(([k]) => k.includes("核验"))?.[1] as string | undefined)
    : undefined;
  const status = d?.formula?.status || d?.metric?.status;
  const kind = d?.kind === "fact" ? "事实" : d?.kind === "metric" ? "指标" : meta?.kind || "引用";
  const title = d?.title || meta?.label;
  const value = d?.value_display || d?.metric?.display || d?.fact?.value_text;
  const statusText =
    status === "OK"
      ? "算式已核"
      : status === "MISMATCH"
        ? "算式待核"
        : audit === "SUPERSEDED"
          ? "已校正"
          : status || "原件已定位";

  return (
    <>
      <span
        ref={ref}
        className={"chip cite" + (tip ? " active" : "")}
        onClick={() => {
          close();
          onRef(r);
        }}
        onMouseEnter={open}
        onMouseLeave={leaveChip}
        onFocus={open}
        onBlur={close}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            close();
            onRef(r);
          }
        }}
        tabIndex={0}
        role="button"
        aria-label={`查看引用：${meta?.label || "证据"}`}
        title={meta?.label || "查看依据"}
      >
        <span className="k">{meta?.kind || "引用"}</span>
        {meta?.label || "查看依据"}
        <span className="cite-dot" />
      </span>
      {tip && createPortal(
        <div
          ref={tipRef}
          className={"cite-tip" + (tip.loading ? " is-loading" : "")}
          style={{ left: tip.x, top: tip.y }}
          onMouseEnter={() => {
            over.current = true;
            clearLinger();
          }}
          onMouseLeave={leaveChip}
          onClick={() => {
            close();
            onRef(r);
          }}
          role="dialog"
          aria-label="引用预览"
        >
          <div className="ct-h">
            <span className="ct-k">{kind}</span>
            <span
              className={
                "ct-st " +
                (status === "OK" ? "ok" : audit === "SUPERSEDED" ? "warn" : "")
              }
            >
              {statusText}
            </span>
            <span className="ct-spacer" />
            <span className="ct-ref">证据引用</span>
          </div>

          {tip.loading ? (
            <div className="ct-sk" aria-label="正在读取原件">
              <i /><i /><i />
            </div>
          ) : (
            <>
              {value && <div className="ct-v mono">{value}</div>}
              {title && <div className="ct-title">{title}</div>}
              {doc?.title && <div className="ct-doc">{doc.title}</div>}
              <div className="ct-meta">
                {loc?.page && <span>P{loc.page}</span>}
                {loc?.cell_id && <span>原表单元格</span>}
                {doc?.published_on && <span>{doc.published_on}</span>}
                {d?.basis?.["口径"] && <span>{d.basis["口径"]}</span>}
              </div>
              {d?.formula?.text && <div className="ct-formula mono">{d.formula.text}</div>}
              {audit === "SUPERSEDED" && <div className="ct-flag">该值已被后续更正公告替代</div>}
              {d?.excerpt && <div className="ct-ex">“{String(d.excerpt).slice(0, 100)}”</div>}
            </>
          )}

          <div className="ct-f">
            <span><b>点击</b> 打开四层证据</span>
            <span className="mono">Esc 关闭</span>
          </div>
          <span className="ct-caret" aria-hidden />
        </div>,
        document.body,
      )}
    </>
  );
}

function Chips({ refs, index, onRef }: { refs: string[]; index: any; onRef: (r: string) => void }) {
  if (!refs?.length) return null;
  return (
    <div className="chips">
      {Array.from(new Set(refs)).map((r) => (
        <CiteChip key={r} r={r} meta={index?.[r]} onRef={onRef} />
      ))}
    </div>
  );
}

function Paras({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  return (
    <>
      {(sec.paragraphs || []).map((p: any, i: number) => (
        <div className={"para" + (p.refs?.length ? " cited" : "")} key={i}>
          <p>{p.text}</p>
          <Chips refs={p.refs} index={sec.ref_index} onRef={onRef} />
        </div>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ */

function Overview({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  return (
    <>
      <div className="kpis">
        {(sec.kpis || []).map((k: any, i: number) => (
          <div
            className="kpi"
            key={i}
            onClick={() => k.ref && onRef(k.ref)}
            title={k.formula || ""}
            style={{ opacity: k.status === "OK" ? 1 : 0.75 }}
          >
            <div className="lab">
              <span>{k.label}</span>
              <span className="pill" style={{ fontSize: 9 }}>{k.status === "OK" ? (CONF_LABEL[k.confidence] || "—") : (STATUS_LABEL[k.status] || "缺证")}</span>
            </div>
            <div className={"val" + (k.value ? "" : " na")}>{k.value || "缺证"}</div>
            <div className="fx">{k.formula}</div>
          </div>
        ))}
      </div>
      {sec.ai_brief && (
        <div className="ai-brief">
          <div className="ai-brief-h"><span>AI 阅读提示</span><em>仅提示阅读顺序，不参与结论</em></div>
          <p>{sec.ai_brief}</p>
        </div>
      )}
      <Paras sec={sec} onRef={onRef} />
      <div className="chips" style={{ marginTop: 4 }}>
        {(sec.highlights || []).map((h: any) => (
          <span className="chip" key={h.rule} style={{ cursor: "default" }}>
            <span className={"pill " + h.status} style={{ fontSize: 9 }}>{h.status}</span>
            <span style={{ maxWidth: "min(320px, 56vw)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.headline}</span>
          </span>
        ))}
      </div>
    </>
  );
}

function Financials({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  const years = useMemo(() => {
    const ys = new Set<number>();
    (sec.rows || []).forEach((r: any) => r.series.forEach((s: any) => ys.add(s.year)));
    return Array.from(ys).sort();
  }, [sec]);

  return (
    <>
      <Paras sec={sec} onRef={onRef} />
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table className="tb">
          <thead>
            <tr>
              <th>指标 · 公式</th>
              {years.map((y) => <th key={y}>FY{y}</th>)}
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {(sec.rows || []).map((r: any) => (
              <tr key={r.metric_code}>
                <td className="lab">
                  {r.label}
                  <br />
                  <small>{r.formula}　<span style={{ color: "var(--dim)" }}>{r.formula_id}</span></small>
                </td>
                {years.map((y) => {
                  const s = r.series.find((x: any) => x.year === y);
                  if (!s || !s.display) return <td key={y}><span className="na">—</span></td>;
                  return (
                    <td key={y} className="clickable" onClick={() => s.ref && onRef(s.ref)}>
                      {s.display}
                    </td>
                  );
                })}
                <td>
                  <span className={"pill " + (r.status === "OK" ? "OK" : "WARN")} style={{ fontSize: 9 }}>
                    {r.status === "OK" ? (CONF_LABEL[r.confidence] || "—") : (STATUS_LABEL[r.status] || "缺证")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="note">{sec.note}</div>
    </>
  );
}

function Peer({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  const roster = (sec.rows?.[0]?.cells || []).map((c: any) => ({ id: c.entity_id, name: c.name }));
  const radar = useMemo(() => {
    const rows = sec.rows || [];
    if (rows.length < 3 || roster.length < 2) return null;
    const dims = rows.map((r: any) => ({ name: r.label, max: Math.max(...r.cells.map((c: any) => parseFloat(String(c.display || "0")) || 0)) * 1.25 || 60 }));
    const series = roster.map((co: any, i: number) => ({
      name: co.name,
      value: rows.map((r: any) => {
        const c = r.cells.find((x: any) => x.entity_id === co.id);
        return parseFloat(String(c?.display || "0")) || 0;
      }),
      itemStyle: { color: ["#d6fb6a", "#e8c583", "#8fa3c8"][i % 3] },
      areaStyle: { opacity: i === 0 ? 0.18 : 0.05 },
      lineStyle: { width: 1.6 },
    }));
    return {
      backgroundColor: "transparent",
      tooltip: { backgroundColor: "#12151a", borderColor: "rgba(255,255,255,.12)", textStyle: { color: "#e7e9ee", fontSize: 11 } },
      legend: { bottom: 0, textStyle: { color: "#8b93a1", fontSize: 10 }, itemWidth: 8, itemHeight: 8 },
      radar: {
        indicator: dims, radius: "62%", center: ["50%", "46%"], splitNumber: 3,
        axisName: { color: "#8b93a1", fontSize: 10 },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
        splitArea: { areaStyle: { color: ["rgba(255,255,255,.015)", "transparent"] } },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.1)" } },
      },
      series: [{ type: "radar", symbolSize: 3, data: series }],
    };
  }, [sec, roster]);

  return (
    <>
      <Paras sec={sec} onRef={onRef} />
      <div className="tw">
      <table className="tb">
        <thead>
          <tr>
            <th>指标</th>
            {(sec.rows?.[0]?.cells || []).map((c: any) => <th key={c.entity_id}>{c.name}</th>)}
            <th>中位数</th>
            <th>n</th>
          </tr>
        </thead>
        <tbody>
          {(sec.rows || []).map((r: any) => (
            <tr key={r.metric_code}>
              <td className="lab">{r.label}</td>
              {r.cells.map((c: any) => (
                <td
                  key={c.entity_id}
                  className={c.ref ? "clickable" : ""}
                  onClick={() => c.ref && onRef(c.ref)}
                >
                  {c.display || <span className="na">{STATUS_LABEL[c.status] || "缺证"}</span>}
                  {c.source === "eastmoney" && (
                    <span className="src-tag" title="该同业指标未从年报原件抽到，暂用第三方结构化数据">三方</span>
                  )}
                </td>
              ))}
              <td>{r.median_display || <span className="na">{r.n < 2 ? "不适用" : "—"}</span>}</td>
              <td>{r.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {radar && (
        <div className="peer-radar">
          <div className="pr-h">
            <b>同业轮廓</b>
            <span>三个指标同一财年、同一口径；面积大不等于更好</span>
          </div>
          <Chart option={radar} height={260} />
        </div>
      )}
      <div className="note">{sec.n_note}</div>
    </>
  );
}

function Risk({ sec }: { sec: any }) {
  const rules = sec.rules || [];
  const triggered = rules.filter((r: any) => r.status === "TRIGGERED").length;
  return (
    <>
      <div className="risk-strip">
        {rules.map((r: any) => (
          <div className={"risk-cell " + r.status} key={r.rule_id}>
            <span className="rc-status">{r.status === "TRIGGERED" ? "触发" : r.status === "NOT_EVALUABLE" ? "不可评估" : "未触发"}</span>
            <b>{r.label}</b>
            <span className="rc-line">{r.headline}</span>
          </div>
        ))}
        <div className={"risk-summary" + (triggered ? " warn" : "")}>
          <b>{triggered}</b>
          <span>条规则触发</span>
          <em>未触发 ≠ 无风险</em>
        </div>
      </div>
      {rules.map((r: any) => (
        <div className={"rule" + (r.status === "TRIGGERED" ? " on" : "")} key={r.rule_id}>
          <div className="hd">
            <span className={"pill " + r.status}>{STATUS_LABEL[r.status] || r.status}</span>
            <b>{r.label}</b>
            {r.enhanced && <span className="pill WARN" style={{ fontSize: 9 }}>增强</span>}
          </div>
          <div className="txt">{r.headline}</div>
          <div className="kv">
            <span className="k">阈值</span><span>{r.threshold_text}</span>
            <span className="k">潜在影响</span><span>{r.potential_impact}</span>
            <span className="k">反证 / 反例</span><span>{r.counter_evidence}</span>
            <span className="k">下一份材料</span><span>{r.next_material}</span>
            {r.missing?.length > 0 && <><span className="k">缺失输入</span><span style={{ color: "var(--warn)" }}>{r.missing.join("、")}</span></>}
          </div>
        </div>
      ))}
      <Paras sec={sec} onRef={() => {}} />
    </>
  );
}

function Industry({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  const sample = sec.sample || [];
  const members = sec.members || [];
  const option = useMemo(() => ({
    backgroundColor: "transparent",
    grid: { left: 46, right: 46, top: 30, bottom: 26 },
    tooltip: {
      trigger: "axis", backgroundColor: "#101318", borderColor: "#2a2f37",
      textStyle: { color: "#f3f4f6", fontSize: 11 }, borderWidth: 1,
    },
    legend: { textStyle: { color: "#a3a9b4", fontSize: 10.5 }, top: 0, right: 0, itemWidth: 9, itemHeight: 9 },
    xAxis: {
      type: "category", data: sample.map((x: any) => String(x.year)), boundaryGap: true,
      axisLine: { lineStyle: { color: "rgba(255,255,255,.12)" } },
      axisTick: { show: false }, axisLabel: { color: "#8b93a0", fontSize: 10.5 },
    },
    yAxis: [
      {
        type: "value", name: "亿元", nameTextStyle: { color: "#5c636e", fontSize: 9.5 },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } },
        axisLabel: { color: "#8b93a0", fontSize: 10, formatter: (v: number) => v.toFixed(0) },
      },
      {
        type: "value", name: "%", position: "right", scale: true,
        nameTextStyle: { color: "#5c636e", fontSize: 9.5 }, splitLine: { show: false },
        axisLabel: { color: "#8b93a0", fontSize: 10 },
      },
    ],
    series: [
      {
        name: "样本营收合计", type: "bar", barWidth: 22,
        data: sample.map((x: any) => (x.revenue_sum ? x.revenue_sum / 1e8 : null)),
        itemStyle: {
          borderRadius: [3, 3, 0, 0],
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: "rgba(232,197,131,.8)" }, { offset: 1, color: "rgba(232,197,131,.16)" }],
          },
        },
      },
      {
        name: "样本毛利率", type: "line", yAxisIndex: 1, smooth: true, symbolSize: 5,
        data: sample.map((x: any) => x.gross_margin_pct),
        lineStyle: { color: "#d6fb6a", width: 1.8 }, itemStyle: { color: "#d6fb6a" },
      },
    ],
  }), [sample]);

  return (
    <>
      <Paras sec={sec} onRef={onRef} />
      {sample.length > 0 && <Chart option={option} height={250} />}
      {members.length > 0 && (
        <div className="tw" style={{ marginTop: 12 }}>
          <table className="tb">
            <thead>
              <tr><th>样本公司</th><th>定位</th><th>2025 营收</th><th>毛利率</th></tr>
            </thead>
            <tbody>
              {members.map((m: any) => (
                <tr key={m.entity_id}>
                  <td className="lab">{m.name}<br /><small className="mono">{m.ticker}</small></td>
                  <td>{m.tag || m.role || "—"}</td>
                  <td className="mono">{m.latest_revenue ? `${(Number(m.latest_revenue) / 1e8).toFixed(0)} 亿` : "—"}</td>
                  <td className="mono">{m.latest_gm != null ? `${m.latest_gm}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="note">{sec.n_note}</div>
    </>
  );
}

function Operations({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  const d = (sec.decomposition || [])[0];
  const option = useMemo(() => {
    if (!d) return {};
    const items = [
      { name: "上年毛利率", value: null },
      { name: "结构项", value: Number(d.structure_pp) },
      { name: "分部毛利率项", value: Number(d.margin_pp) },
      { name: "残差", value: Number(d.residual_pp) },
      { name: "本年变动", value: Number(d.total_pp) },
    ];
    let base = 0;
    const data = items.map((it, i) => {
      if (i === 0) return { value: 0, itemStyle: { color: "transparent" } };
      if (i === items.length - 1) return { value: it.value, itemStyle: { color: "#d6fb6a", borderRadius: 3 } };
      const start = base;
      base += it.value ?? 0;
      return {
        value: it.value,
        itemStyle: { color: (it.value ?? 0) >= 0 ? "#6fe3b0" : "#ff7a6b", borderRadius: 3 },
        baseValue: start,
      };
    });
    return {
      backgroundColor: "transparent",
      grid: { left: 42, right: 16, top: 18, bottom: 26 },
      tooltip: {
        trigger: "item", backgroundColor: "#101318", borderColor: "#2a2f37",
        textStyle: { color: "#f3f4f6", fontSize: 11 },
        formatter: (p: any) => `${p.name}<br/>${p.value > 0 ? "+" : ""}${p.value} pp`,
      },
      xAxis: {
        type: "category", data: items.map((i) => i.name),
        axisLabel: { color: "#8b93a0", fontSize: 10 },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.12)" } }, axisTick: { show: false },
      },
      yAxis: {
        type: "value", name: "pp", nameTextStyle: { color: "#5c636e", fontSize: 9.5 },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } },
        axisLabel: { color: "#8b93a0", fontSize: 10 },
      },
      series: [{ type: "bar", stack: "b", data, barWidth: 32 }],
    };
  }, [d]);

  return (
    <>
      {(sec.drivers || []).length > 0 && (
        <div className="kpis" style={{ gridTemplateColumns: "repeat(2,1fr)" }}>
          {sec.drivers.map((d2: any) => (
            <div className="kpi" key={d2.name} onClick={() => d2.ref && onRef(d2.ref)}>
              <div className="lab"><span>{d2.name}</span></div>
              <div className="val">{d2.value || "缺证"}</div>
            </div>
          ))}
        </div>
      )}
      <Paras sec={sec} onRef={onRef} />
      {d ? (
        <div className="panel tight" style={{ marginTop: 8 }}>
          <div className="panel-h">
            <h3>毛利率变动恒等分解 · FY{d.year}</h3>
            <span className="hint">{d.check}</span>
          </div>
          <Chart option={option} height={230} />
          <div className="sub" style={{ fontSize: 11 }}>{d.note}</div>
        </div>
      ) : (
        <div className="empty">分部数据不齐或勾稽未通过，本版不做结构分解（拒绝在不完整口径上做归因）。</div>
      )}
    </>
  );
}

function Chain({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  return (
    <>
      <Paras sec={sec} onRef={onRef} />
      {sec.ai_brief && (
        <div className="ai-brief">
          <div className="ai-brief-h"><span>AI 产业链提示</span><em>仅提示传导路径，不参与结论</em></div>
          <p>{sec.ai_brief}</p>
        </div>
      )}
      {sec.nodes?.length ? (
        <div style={{ border: "1px solid var(--line)", borderRadius: 14, padding: "10px 12px 6px", marginTop: 10 }}>
          <ChainGraph nodes={sec.nodes} edges={sec.edges} metrics={sec.metrics} height={520} />
        </div>
      ) : (
        <div className="empty">该行业暂无产业链数据</div>
      )}
      <div className="note">{sec.n_note || "关系边标注依据；推断关系不应被当作披露事实。"}</div>
    </>
  );
}

function DataQuality({ sec, onRef }: { sec: any; onRef: (r: string) => void }) {
  // groups 现在是聚合后的列表：每项带 count / pages / explanation
  const groups: any[] = Array.isArray(sec.groups) ? sec.groups : [];
  const summary = sec.summary || {};
  const totalIssues = groups.reduce((a: number, g: any) => a + (g.count || 0), 0) || 1;
  return (
    <>
      <div className="grid cols-3" style={{ marginBottom: 14 }}>
        {(sec.coverage || []).map((c: any) => (
          <div className="panel tight" key={c.label}>
            <div className="big-stat">
              <span className="n">{c.value}<span style={{ fontSize: 11, color: "var(--dim)", marginLeft: 3 }}>{c.unit}</span></span>
              <span className="l">{c.label}</span>
            </div>
          </div>
        ))}
      </div>
      <Paras sec={sec} onRef={onRef} />

      {groups.length > 0 && (
        <div className="dq-types">
          {groups.slice(0, 6).map((g: any, i: number) => (
            <div className="dq-type" key={i}>
              <span className="dq-label">{g.label || g.type}</span>
              <span className="dq-bar"><i style={{ width: `${Math.max(3, ((g.count || 0) / totalIssues) * 100)}%` }} /></span>
              <span className="dq-n mono">×{g.count}</span>
            </div>
          ))}
        </div>
      )}

      {groups.length > 0 && (
        <div className="panel tight" style={{ marginTop: 6 }}>
          <div className="panel-h">
            <h3>质量问题（已按原因合并）</h3>
            <span className="hint">
              {summary.groups || groups.length} 类 · 原始 {summary.items || "—"} 条
              {summary.merged_away ? ` · 合并掉 ${summary.merged_away} 条重复` : ""}
            </span>
          </div>
          {groups.slice(0, 8).map((g: any, i: number) => (
            <div key={i} className="qgroup">
              <span className={"pill " + g.severity} style={{ fontSize: 9 }}>{g.label || ISSUE_LABEL[g.type] || "资料问题"}</span>
              <span className="qtext">{g.explanation || ISSUE_LABEL[g.type] || "资料问题"}</span>
              <span className="qcount">×{g.count}</span>
              {g.pages?.length > 0 && (
                <span className="qpages">P{g.pages.slice(0, 8).join("、P")}{g.pages.length > 8 ? "…" : ""}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {(sec.blocked_claims || []).length > 0 && (
        <div className="panel tight" style={{ marginTop: 12, borderColor: "rgba(255,122,107,.24)" }}>
          <div className="panel-h"><h3>被审核阻断的结论</h3><span className="hint">不进入正文，保留原因</span></div>
          {sec.blocked_claims.map((b: any, i: number) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div className="quote" style={{ marginTop: 4 }}>{b.text}</div>
              {b.findings.map((f: any, j: number) => (
                <div key={j} className="sub" style={{ fontSize: 11 }}>· {f.detail}</div>
              ))}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

export default function ReportView({ data, onRef, subject, right, onOpenProvenance }: Props) {
  const secs = data?.sections || [];
  const active = useActiveSection(ORDER.filter((k) => secs.some((s: any) => s.section_key === k)));
  const [evidenceMode, setEvidenceMode] = useState(false);
  const demoRef = useMemo(() => {
    const k = secs.find((s: any) => s.section_key === "overview")?.content?.kpis?.find((k: any) => k.ref)?.ref;
    if (k) return k;
    for (const s of secs) {
      for (const p of s.content?.paragraphs || []) {
        if (p.refs?.length) return p.refs[0];
      }
    }
    return null;
  }, [secs]);

  if (!data) return <div className="empty">还没有正式版本。先在「运行台」跑一次研究。</div>;

  const render: Record<string, any> = {
    overview: Overview, industry: Industry, operations: Operations, financials: Financials,
    peer: Peer, risk: Risk, chain: Chain, data_quality: DataQuality,
  };
  const claims = data.claims || [];
  const pending = claims.filter((c: any) => c.verdict !== "PASS").length;
  const refsN = claims.reduce((a: number, c: any) => a + (c.refs?.length || 0), 0);
  const allParas = secs.flatMap((s: any) => s.content?.paragraphs || []);
  const citedParas = allParas.filter((p: any) => p.refs?.length).length;
  const dq = secs.find((s: any) => s.section_key === "data_quality")?.content;
  const docsN = (dq?.coverage || []).find((c: any) => c.label === "原件")?.value || "—";

  const exportMd = () => {
    const md = secs.map((s: any) => `## ${s.content.title}\n\n` +
      (s.content.paragraphs || []).map((p: any) => p.text).join("\n\n")).join("\n\n");
    const blob = new Blob([`# ${subject?.name || ""} · 年度经营研究\n\n${md}`], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${subject?.name || "report"}_v${data.version.version_no}.md`;
    a.click();
  };

  return (
    <div className={"report-shell" + (evidenceMode ? " evidence-on" : "")}>
      <aside className="toc">
        <div className="toc-t">Contents</div>
        {ORDER.map((key, i) => {
          const sec = secs.find((s: any) => s.section_key === key);
          if (!sec) return null;
          const nRefs = (sec.content.paragraphs || []).reduce((a: number, p: any) => a + (p.refs?.length || 0), 0);
          return (
            <a
              key={key}
              href={`#${key}`}
              className={active === key ? "on" : ""}
              onClick={(ev) => {
                ev.preventDefault();
                document.getElementById(key)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              <span className="n">{String(i + 1).padStart(2, "0")}</span>
              <span className="t">{sec.content.title}</span>
              <span className="d">{nRefs ? `${nRefs}` : ""}</span>
            </a>
          );
        })}
        <div className="toc-foot">
          {secs.length} 节 · {claims.length} 条结论<br />
          v{data.version.version_no} · {data.version.state}<br />
          <span style={{ color: "var(--ev)" }}>{pending} 条待核</span>
        </div>
        <button className="toc-provenance" onClick={onOpenProvenance}>
          打开证据地图 <ArrowUpRight size={11} />
        </button>
      </aside>

      <div>
        <header className="report-head">
          <div className="rh-top">
            <span className="rh-seal">工商银行企业命题二</span>
            <span className="pill HIGH">v{data.version.version_no} · {data.version.state === "published" ? "已发布" : "草稿"}</span>
            <span className="pill">截止 {data.version.as_of}</span>
            {pending > 0 && <span className="pill WARN">{pending} 条待核</span>}
            <span className="spacer" />
            <button
              className={"btn sm " + (evidenceMode ? "primary" : "ghost")}
              onClick={() => setEvidenceMode((v) => !v)}
              title="只高亮有引用的段落，其余变暗"
            >
              {evidenceMode ? "退出证据模式" : "证据模式"}
            </button>
            <button className="btn sm" onClick={onOpenProvenance}>证据地图 <ArrowUpRight size={11} /></button>
            <button className="btn sm ghost" onClick={exportMd}>导出 MD</button>
          </div>
          <h1>{subject?.name || "公司"} · 年度经营研究</h1>
          <div className="rh-sub">
            {subject?.exchange}:{subject?.ticker} · 合并口径 · {secs.length} 个章节 · 样本内同业比较
          </div>
          <div className="rh-ribbon">
            <div><span>结论</span><b>{claims.length}</b></div>
            <div><span>引用</span><b>{refsN}</b></div>
            <div><span>来源文档</span><b>{docsN}</b></div>
            <div><span>待核</span><b className={pending ? "warn" : ""}>{pending}</b></div>
          </div>
          <div className="ec-hint">
            <span className="ec-hint-t"><i />四层证据链</span>
            <div className="ec-hint-steps">
              {["口径", "算式", "单元格", "原件"].map((s, i) => (
                <span className="ec-hint-step" style={{ animationDelay: `${i * 0.14}s` }} key={s}>
                  <i>{i + 1}</i>{s}{i < 3 && <em>→</em>}
                </span>
              ))}
            </div>
            <span className="ec-hint-note">从值到原件，逐层收窄</span>
            <span className="spacer" />
            <button
              className="ec-hint-play"
              onClick={() => demoRef && onRef(demoRef)}
              title="打开一条引用的四层证据"
              disabled={!demoRef}
            >
              <Play size={9} /> 演示一条
            </button>
          </div>
          {evidenceMode && (
            <div className="evidence-banner">
              <span className="eb-dot" />
              <b>证据模式</b>
              <span>{citedParas} / {allParas.length} 段有引用；未引用段落已压暗，避免把叙述当成证据。</span>
              <span className="spacer" />
              <span className="mono">点击任意引用可回到原页</span>
            </div>
          )}
          <div className="rh-meta">
            <span>报告编号 <b>{data.version.content_hash.slice(0, 12)}</b></span>
            <span>生成日期 <b>{String(data.version.created_at || "").slice(0, 10)}</b></span>
            <span>观察截止 <b>{data.version.as_of}</b></span>
          </div>
        </header>

        {ORDER.map((key, i) => {
          const sec = secs.find((s: any) => s.section_key === key);
          if (!sec) return null;
          const C = render[key];
          return (
            <section className="sec" id={key} key={key}>
              <div className="sec-head">
                <span className="no">{String(i + 1).padStart(2, "0")}</span>
                <h2>{sec.content.title}</h2>
                <span className="h">本版已核</span>
              </div>
              <C sec={sec.content} onRef={onRef} />
            </section>
          );
        })}
      </div>

      <div className="ask-rail">{right}</div>
    </div>
  );
}
