import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import Chart from "../components/Chart";
import ChainGraph from "../components/ChainGraph";
import { Reveal } from "../components/motion";
import { ArrowUpRight } from "../components/icons";

const FORMULA = {
  revenue: (v: number) => `${(v / 1e8).toFixed(1)} 亿`,
  pct: (v: number | null) => (v == null ? "—" : `${v.toFixed(2)}%`),
};

export default function IndustryView({
  initial,
  industries,
  onPickSubject,
}: {
  initial?: string;
  industries: any[];
  onPickSubject?: (entityId: string) => void;
}) {
  const [cur, setCur] = useState(initial || industries[0]?.id || "beer");
  const [panel, setPanel] = useState<any>(null);
  const [chain, setChain] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [matrix, setMatrix] = useState<any>(null);
  const [relFilter, setRelFilter] = useState("all");

  useEffect(() => {
    api.industryMatrix(2025).then(setMatrix).catch(() => {});
  }, []);

  useEffect(() => {
    if (initial && initial !== cur) setCur(initial);
  }, [initial]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([api.industry(cur), api.chain(cur, 2025)])
      .then(([p, c]) => {
        if (!alive) return;
        setPanel(p);
        setChain(c);
      })
      .catch(() => {})
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [cur]);

  const years = panel?.years || [2022, 2023, 2024, 2025];
  const members = panel?.members || [];
  const summary = panel?.summary || [];
  const latest = summary[summary.length - 1] || {};

  const trendOption = useMemo(() => {
    const names = members.map((m: any) => m.name);
    const colors = ["#d6fb6a", "#e8c583", "#8fa3c8"];
    return {
      backgroundColor: "transparent",
      grid: { left: 46, right: 18, top: 34, bottom: 26 },
      tooltip: { trigger: "axis", backgroundColor: "#12151a", borderColor: "rgba(255,255,255,.12)", textStyle: { color: "#e7e9ee", fontSize: 11 } },
      legend: { data: names, top: 0, right: 0, itemWidth: 8, itemHeight: 8, textStyle: { color: "#8b93a1", fontSize: 10 } },
      xAxis: {
        type: "category", data: years.map(String), boundaryGap: false,
        axisLine: { lineStyle: { color: "rgba(255,255,255,.12)" } },
        axisLabel: { color: "#6b7280", fontSize: 10 },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value", name: "亿元", scale: true, splitNumber: 4,
        nameTextStyle: { color: "#5c6b80", fontSize: 9 },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } },
        axisLabel: { color: "#6b7280", fontSize: 9, formatter: (v: number) => (v / 1e8).toFixed(0) },
      },
      series: members.map((m: any, i: number) => ({
        name: m.name, type: "line", smooth: true, symbolSize: 4,
        data: (m.revenue || []).map((p: any) => (p.value ? Number(p.value) : null)),
        lineStyle: { width: 1.8, color: colors[i % colors.length] },
        itemStyle: { color: colors[i % colors.length] },
        areaStyle: i === 0 ? { opacity: 0.08, color: colors[0] } : undefined,
      })),
    };
  }, [members, years]);

  const gmOption = useMemo(() => ({
    backgroundColor: "transparent",
    grid: { left: 38, right: 12, top: 18, bottom: 26 },
    tooltip: { trigger: "axis", backgroundColor: "#12151a", borderColor: "rgba(255,255,255,.12)", textStyle: { color: "#e7e9ee", fontSize: 11 } },
    xAxis: {
      type: "category", data: years.map(String),
      axisLine: { lineStyle: { color: "rgba(255,255,255,.12)" } },
      axisLabel: { color: "#6b7280", fontSize: 10 }, axisTick: { show: false },
    },
    yAxis: {
      type: "value", min: 0, max: 60, splitNumber: 3,
      splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } },
      axisLabel: { color: "#6b7280", fontSize: 9, formatter: "{value}%" },
    },
    series: [
      {
        name: "样本毛利率", type: "bar", barWidth: 18,
        data: summary.map((s: any) => s.gross_margin_pct),
        itemStyle: {
          borderRadius: [3, 3, 0, 0],
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: "rgba(214,251,106,.85)" }, { offset: 1, color: "rgba(214,251,106,.18)" }],
          },
        },
      },
    ],
  }), [summary, years]);

  const nodeNames: Record<string, string> = Object.fromEntries(
    (chain?.nodes || []).map((n: any) => [n.node_id, n.name]),
  );

  return (
    <div className="view-enter">
      <div className="ind-head">
        <div>
          <div className="kicker" style={{ marginBottom: 6 }}>行业样本 · 公开数据</div>
          <h1>{panel?.industry?.name || "行业"}</h1>
        </div>
        <div className="sub">
          {members.length || 3} 家可比公司，同一年度、同一合并口径。
          财务数据来自第三方结构化接口，产业链关系来自公开资料，均已标注来源。
        </div>
        <div className="ind-switch">
          {industries.map((i: any) => (
            <button key={i.id} className={"ind-pill" + (cur === i.id ? " on" : "")} onClick={() => setCur(i.id)}>
              {i.name}
            </button>
          ))}
        </div>
      </div>

      <div className="ind-kpis">
        {[
          { v: latest.revenue_sum ? `${(latest.revenue_sum / 1e8).toFixed(0)} 亿` : "—", l: `2025 样本营收合计（n=${latest.n || 0}）` },
          { v: FORMULA.pct(latest.gross_margin_pct), l: "2025 样本毛利率" },
          { v: FORMULA.pct(latest.debt_ratio_pct), l: "2025 样本资产负债率" },
        ].map((k) => (
          <div className="ind-kpi" key={k.l}>
            <div className="v">{k.v}</div>
            <div className="l">{k.l}</div>
          </div>
        ))}
      </div>

      {matrix?.rows?.length > 0 && (
        <div className="imx">
          <div className="imx-head">
            <b>六个行业横截面</b>
            <span>FY2025 样本口径（n=3）· 点一列切换行业 · 数值来自第三方结构化数据</span>
          </div>
          <div className="imx-grid">
            {matrix.rows.map((r: any) => {
              const gm = r.gross_margin_pct;
              const g = r.growth_pct;
              return (
                <button
                  key={r.industry}
                  className={"imx-col" + (cur === r.industry ? " on" : "")}
                  onClick={() => setCur(r.industry)}
                >
                  <span className="imx-name">{r.name}</span>
                  <span className={"imx-v " + (g == null ? "" : g >= 0 ? "up" : "down")}>
                    {g == null ? "—" : `${g > 0 ? "+" : ""}${g.toFixed(1)}%`}
                  </span>
                  <span className="imx-l">营收同比</span>
                  <span className="imx-bar"><i style={{ width: `${Math.max(4, Math.min(100, (gm || 0)))}%` }} /></span>
                  <span className="imx-v">{gm == null ? "—" : `${gm.toFixed(1)}%`}</span>
                  <span className="imx-l">毛利率</span>
                  <span className="imx-v dim">{r.debt_ratio_pct == null ? "—" : `${r.debt_ratio_pct.toFixed(1)}%`}</span>
                  <span className="imx-l">资产负债率</span>
                </button>
              );
            })}
          </div>
          <div className="imx-note">柱长 = 毛利率；红色/绿色只表示同比方向，不是涨跌建议。</div>
        </div>
      )}

      <div className="ind-grid">
        <div className="ind-card">
          <h3>营业收入（亿元）</h3>
          <div className="sub">同比增速以样本合计计算；单家公司的波动可能被规模差异掩盖。</div>
          <Chart option={trendOption} height={250} />
        </div>
        <div className="ind-card">
          <h3>样本毛利率</h3>
          <div className="sub">按样本合计收入与成本计算，不是三家公司毛利率的简单平均。</div>
          <Chart option={gmOption} height={250} />
        </div>
      </div>

      <div className="ind-card" style={{ marginTop: 16 }}>
        <h3>同业对比</h3>
        <div className="sub">点公司名进入该公司的研究；红色标记为当前样本主体。</div>
        <table className="co-table">
          <thead>
            <tr>
              <th>公司</th><th>定位</th>
              <th style={{ textAlign: "right" }}>2025 营收</th>
              <th style={{ textAlign: "right" }}>同比</th>
              <th style={{ textAlign: "right" }}>毛利率</th>
              <th style={{ textAlign: "right" }}>较上年</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {members.map((m: any) => {
              const g = m.gross_margin || [];
              const curG = g[g.length - 1]?.value;
              const prevG = g[g.length - 2]?.value;
              const d = curG != null && prevG != null ? (curG - prevG).toFixed(2) : null;
              return (
                <tr key={m.entity_id}>
                  <td>
                    <b style={{ fontSize: 12.5 }}>{m.name}</b>
                    <span className="mono" style={{ color: "var(--dim)", fontSize: 9.5, marginLeft: 7 }}>{m.ticker}</span>
                  </td>
                  <td style={{ color: "var(--dim)", fontSize: 11 }}>{m.tag || m.role}</td>
                  <td className="num">{m.latest_revenue ? FORMULA.revenue(Number(m.latest_revenue)) : "—"}</td>
                  <td className="num" style={{ color: "var(--muted)" }}>
                    {(() => {
                      const r = m.revenue || [];
                      const a = r[r.length - 1]?.value, b = r[r.length - 2]?.value;
                      return a && b ? `${((Number(a) / Number(b) - 1) * 100).toFixed(1)}%` : "—";
                    })()}
                  </td>
                  <td className="num">{FORMULA.pct(m.latest_gm)}</td>
                  <td className="num" style={{ color: d && Number(d) < 0 ? "var(--ok)" : "var(--muted)" }}>
                    {d ? `${Number(d) > 0 ? "+" : ""}${d} pp` : "—"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn ghost sm" style={{ padding: "3px 8px" }} onClick={() => onPickSubject?.(m.entity_id)}>
                      研究 <ArrowUpRight size={10} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Reveal>
        <div className="ind-card" style={{ marginTop: 16 }}>
          <h3>产业链与关联企业</h3>
          <div className="sub">
            节点是产业角色，边是交易或竞争关系。样本公司位于中游，悬停可看邻接关系，点击看节点说明。
          </div>
          {chain?.nodes?.length ? (
            <>
              <div className="kg-stats">
                <span><b>{chain.nodes.length}</b> 个节点</span>
                <span><b>{chain.edges.length}</b> 条关系</span>
                <span><b>{new Set(chain.edges.map((e: any) => e.relation)).size}</b> 类关系</span>
                <span><b>{chain.nodes.filter((n: any) => n.role === "core").length}</b> 家样本公司</span>
                <span className="spacer" />
                <span className="kg-note">节点按上游 / 包材 / 制造 / 渠道 / 需求分层；每条边均标注依据</span>
              </div>
              <ChainGraph nodes={chain.nodes} edges={chain.edges} metrics={chain.metrics} height={620} />
              <div className="chain-legend">
                <span><i className="cl-solid" />年报 / 行业资料明确</span>
                <span><i className="cl-dash" />行业通用结构</span>
                <span className="spacer" />
                <span className="mono">点击节点查看邻接与依据</span>
              </div>
              <div className="chain-edges">
                <div className="ce-head">
                  <b>关系明细</b>
                  <span>共 {chain.edges.length} 条边；每条边都必须有依据</span>
                  <span className="spacer" />
                  <select value={relFilter} onChange={(e) => setRelFilter(e.target.value)}>
                    <option value="all">全部关系</option>
                    {[...new Set(chain.edges.map((e: any) => e.relation))].map((r: any) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>
                <div className="kg-table">
                  <table className="tb">
                    <thead>
                      <tr><th>关系</th><th>上游 / 起点</th><th>下游 / 终点</th><th>依据</th></tr>
                    </thead>
                    <tbody>
                      {chain.edges.filter((e: any) => relFilter === "all" || e.relation === relFilter).map((e: any) => (
                        <tr key={e.edge_id}>
                          <td><span className="ce-rel">{e.relation}</span></td>
                          <td>{nodeNames[e.src] || e.src}</td>
                          <td>{nodeNames[e.dst] || e.dst}</td>
                          <td style={{ color: "var(--dim)", fontSize: 10 }}>{e.basis || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : (
            <div className="empty" style={{ padding: 30 }}>{loading ? "载入中…" : "该行业暂无产业链数据"}</div>
          )}
        </div>
      </Reveal>

      <div className="note" style={{ marginTop: 12 }}>
        样本合计仅代表这三家公司，不代表行业总量；跨行业比较请使用同一指标与同一年度。
      </div>
    </div>
  );
}
