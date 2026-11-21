import { useEffect, useState } from "react";
import { api } from "../api";
import { ArrowUpRight, File } from "../components/icons";

const FIELD_LABEL: Record<string, string> = {
  revenue: "营业收入", operating_cost: "营业成本", net_profit_parent: "归母净利润",
  total_assets: "资产总计", total_liabilities: "负债合计", total_equity: "所有者权益",
  operating_cashflow: "经营现金流", net_profit_total: "净利润",
  inventories: "存货", receivables: "应收账款",
};
const DECISION_LABEL: Record<string, string> = {
  ACCEPTED: "采用", ACCEPTED_WITH_CONFLICT: "有冲突", BLOCKED: "阻断",
  FROZEN: "冻结", MISSING: "缺失",
};
const STATUS_LABEL: Record<string, string> = {
  OK: "有效", MISSING_INPUT: "缺证", INVALID_BASE: "不可比",
};

export default function VersionsView({ reportId, head, onHeadChange }: any) {
  const [versions, setVersions] = useState<any[]>([]);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [diff, setDiff] = useState<any>(null);
  const [docs, setDocs] = useState<any[]>([]);
  const [staged, setStaged] = useState<string>("");
  const [asOf, setAsOf] = useState("2026-06-30");
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [cur, setCur] = useState<any>(null);

  const load = () => {
    if (!reportId) return;
    api.versions(reportId).then((r) => {
      setVersions(r.versions || []);
      const nums = (r.versions || []).map((v: any) => v.version_no).sort((a: number, b: number) => a - b);
      if (nums.length) {
        // 预览永远基于正式 head，不拿草稿当基线。
        setTo((t) => t ?? (r.head || nums[nums.length - 1]));
        setFrom((f) => f ?? nums[0]);
      }
    });
  };

  useEffect(load, [reportId]);

  useEffect(() => {
    if (!reportId) return;
    api.documents("SH:600600").then((r) => setDocs(r.documents || []));
  }, [reportId]);

  useEffect(() => {
    if (!reportId || to == null) { setCur(null); return; }
    api.version(reportId, to).then(setCur).catch(() => setCur(null));
  }, [reportId, to]);

  useEffect(() => {
    if (!reportId || from == null || to == null || from === to) {
      setDiff(null);
      return;
    }
    api.diff(reportId, from, to).then(setDiff);
  }, [reportId, from, to]);

  const doPreview = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body: any = {
        base_version: to, as_of: asOf, staged_doc_ids: staged ? [staged] : [],
        fiscal_years: [2023, 2024, 2025], peer_ids: ["SH:600132", "SZ:002461"],
      };
      const r = await api.preview(reportId!, body);
      setPreview(r);
      load(); // 让草稿版本立刻出现在时间线上
      if (r.code === "NO_CHANGE") setMsg("输入没有改变任何结论，因此未生成新版本；这本身就是正确结果。");
    } catch (e: any) {
      setMsg(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const doCommit = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      const r = await api.commit(reportId!, preview.draft_version, {
        base_version: preview.base_version,
      });
      setMsg(`已提交：v${r.old_version} → v${r.new_version}，当前版本为 v${r.head}`);
      setPreview(null);
      load();
      onHeadChange?.(r.new_version);
    } catch (e: any) {
      setMsg(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  if (!reportId) return <div className="empty">先运行一次研究，才有版本可比。</div>;

  const changed = (preview?.diff?.sections || diff?.sections || []).filter((s: any) => s.changed).length;

  return (
    <div className="view-enter">
      <div className="page-head">
        <div>
          <h2>版本与补证</h2>
          <div className="desc">版本不可变 · 草稿不会自动替换当前版本 · 发布前校验基线</div>
        </div>
        <div className="spacer" />
        <span className="badge-mode">基线 <b>v{to}</b></span>
        <span className="badge-mode">历史 <b>{versions.length}</b> 个版本</span>
      </div>

      <div className="run-grid">
        <div style={{ display: "grid", gap: 16 }}>
          <div className="panel">
            <div className="panel-h"><h3>版本时间线</h3><span className="hint">点选作为对比基线</span></div>
            <div className="timeline">
              {versions.map((v: any) => (
                <div
                  className={"tl-item" + (to === v.version_no ? " on" : "")}
                  key={v.version_no}
                  onClick={() => setTo(v.version_no)}
                >
                  <div className="tl-top">
                    <b>v{v.version_no}</b>
                    {head === v.version_no && <span className="pill HIGH" style={{ fontSize: 8.5 }}>当前</span>}
                    <span className="pill" style={{ fontSize: 8.5, color: v.state === "published" ? "var(--ok)" : "var(--warn)" }}>
                      {v.state === "published" ? "已发布" : "草稿"}
                    </span>
                    <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--dim)" }}>
                      {v.base_version_id ? `基于 v${v.base_version_id.split("@v")[1]}` : "初始版本"}
                    </span>
                  </div>
                  <div className="tl-sub">截止 {v.as_of} · 编号 {v.content_hash.slice(0, 8)}</div>
                </div>
              ))}
              {versions.length === 0 && <div className="empty">暂无版本</div>}
            </div>
          </div>

          <div className="panel">
            <div className="panel-h"><h3>补证预览</h3><span className="hint">只改受影响的部分</span></div>
            <div className="ver-demo-banner">
              <b>演示材料</b>
              <span>候选更正公告是项目构造的演练文件，明确标注「非真实披露」；真实语料不含这份公告。</span>
            </div>
            <div style={{ display: "grid", gap: 12 }}>
              <div className="field">
                <label>新增材料</label>
                <select value={staged} onChange={(e) => setStaged(e.target.value)}>
                  <option value="">（不加入新材料）</option>
                  {docs.filter((d: any) => d.source_type === "correction").map((d: any) => (
                    <option key={d.document_id} value={d.document_id}>
                      更正公告 · {d.published_on}{d.dataset_tag === "demo_controlled" ? " · 演练" : ""}
                    </option>
                  ))}
                </select>
                {docs.filter((d: any) => d.source_type === "correction").length === 0 && (
                  <div className="field-hint">本库没有更正公告；当前只展示真实年报版本。</div>
                )}
              </div>
              <div className="field">
                <label>观察截止日推进到</label>
                <input type="text" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
                <div className="field-hint">更正公告披露于 2026-06-18，截止日需晚于它才会进入可见范围。</div>
              </div>
              <button className="btn" disabled={busy} onClick={doPreview}>
                {busy ? "计算影响面…" : <><File size={12} /> 生成增量预览</>}
              </button>
              {msg && <div className="note" style={{ margin: 0 }}>{msg}</div>}
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {preview && preview.diff && (
            <div className="panel">
              <div className="panel-h">
                <h3>v{preview.base_version} → v{preview.draft_version} 的影响面</h3>
                <span className="spacer" />
                <span className="pill WARN">{changed} 节改写</span>
              </div>
              <div className="grid cols-3" style={{ marginBottom: 16 }}>
                {[
                  [preview.diff.counts.facts_changed, "个事实变化"],
                  [preview.diff.counts.metrics_changed, "个指标变化"],
                  [preview.diff.counts.sections_changed, "个章节改写"],
                ].map(([n, l]: any) => (
                  <div className="panel tight" key={l}>
                    <div className="big-stat">
                      <span className="n">{n}</span>
                      <span className="l">{l}</span>
                    </div>
                  </div>
                ))}
              </div>

              <div className="ver-impact">
                {(preview.changed_sections || []).map((k: string) => (
                  <span className="vi-chg" key={k}>{k} · 改写</span>
                ))}
                {preview.diff.sections.filter((s: any) => !s.changed).map((s: any) => (
                  <span className="vi-same" key={s.section_key}>{s.section_key} · 版本不变</span>
                ))}
              </div>
              <div className="ver-impact-note">
                影响面按章节依赖关系推算，不是模型猜的；未命中章节沿用同一<span className="mono">章节编号</span>。
                本库实测：{preview.diff.counts.facts_changed} 条事实、{preview.diff.counts.metrics_changed} 个指标变化，
                {changed} 个章节改写、{preview.diff.counts.sections_unchanged} 个章节保持原样。
              </div>

              <div className="diffs">
                {preview.diff.sections.map((s: any) => (
                  <div className="row2" key={s.section_key}>
                    <span className={s.changed ? "chg" : "same"}>{s.title}</span>
                    <span className="sub" style={{ fontSize: 10, color: "var(--dim)" }}>
                      {s.changed ? "本次改写" : "保持原版本"}
                    </span>
                    <span className={"pill " + (s.changed ? "WARN" : "NOT_TRIGGERED")} style={{ fontSize: 8.5 }}>
                      {s.changed ? "已变化" : "未变化"}
                    </span>
                  </div>
                ))}
              </div>

              {preview.diff.metrics.length > 0 && (
                <>
                  <div className="panel-h" style={{ marginTop: 18 }}><h3>指标变化</h3></div>
                  <div className="tw">
                  <table className="tb">
                    <thead><tr><th>指标</th><th>财年</th><th>旧值</th><th>新值</th><th>状态</th></tr></thead>
                    <tbody>
                      {preview.diff.metrics.map((m: any, i: number) => (
                        <tr key={i}>
                          <td className="lab">{m.label}</td>
                          <td>{m.year}</td>
                          <td style={{ color: "var(--dim)" }}>{m.old_display}</td>
                          <td style={{ color: "var(--accent)" }}>{m.new_display}</td>
                          <td>{STATUS_LABEL[m.old_status] || "—"} → {STATUS_LABEL[m.new_status] || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  </div>
                </>
              )}

              {preview.diff.facts.length > 0 && (
                <>
                  <div className="panel-h" style={{ marginTop: 18 }}><h3>数据与判断变化</h3></div>
                  {preview.diff.facts.slice(0, 6).map((f: any, i: number) => (
                    <div className="rule" key={i}>
                      <div className="hd">
                        <span className="pill">{FIELD_LABEL[f.field_code] || f.label || "财务数据"}</span>
                        <span className="mono" style={{ fontSize: 10, color: "var(--dim)" }}>{f.period_end ? `FY${String(f.period_end).slice(0, 4)}` : ""}</span>
                        <span className="pill WARN">{DECISION_LABEL[f.old_decision] || "原判断"} → {DECISION_LABEL[f.new_decision] || "新判断"}</span>
                      </div>
                      <div className="sub mono" style={{ fontSize: 11 }}>
                        {Number(f.old_value || 0).toLocaleString("zh-CN")} → {Number(f.new_value || 0).toLocaleString("zh-CN")}
                      </div>
                      <div className="sub" style={{ fontSize: 11 }}>{f.new_reason}</div>
                    </div>
                  ))}
                </>
              )}

              <div className="hstack" style={{ marginTop: 16 }}>
                <button className="btn primary" disabled={busy} onClick={doCommit}>
                  确认发布 v{preview.draft_version} <ArrowUpRight size={12} />
                </button>
                <span className="sub" style={{ fontSize: 11 }}>草稿不会自动替换当前版本；基线过期时请刷新后重试。</span>
              </div>
            </div>
          )}

          {!preview && (
            <div className="panel">
              <div className="panel-h">
                <h3>章节变化对照</h3>
                <span className="hint">未改写的章节保持原版本</span>
                <span className="spacer" />
                <select value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value))} style={{ padding: "5px 24px 5px 9px", fontSize: 11 }}>
                  {versions.map((v: any) => <option key={v.version_no} value={v.version_no}>对比 v{v.version_no}</option>)}
                </select>
                <select value={to ?? ""} onChange={(e) => setTo(Number(e.target.value))} style={{ padding: "5px 24px 5px 9px", fontSize: 11 }}>
                  {versions.map((v: any) => <option key={v.version_no} value={v.version_no}>基线 v{v.version_no}</option>)}
                </select>
              </div>

              {diff ? (
                <div className="diffs">
                  {diff.sections.map((s: any) => (
                    <div className="row2" key={s.section_key}>
                      <span className={s.changed ? "chg" : "same"}>{s.title}</span>
                      <span className="sub" style={{ fontSize: 10, color: "var(--dim)" }}>
                        {s.changed ? "本次改写" : "保持原版本"}
                      </span>
                      <span className={"pill " + (s.changed ? "WARN" : "NOT_TRIGGERED")} style={{ fontSize: 8.5 }}>
                        {s.changed ? "已变化" : "未变化"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : cur ? (
                <div className="tw">
                <table className="tb">
                  <thead><tr><th>章节</th><th>内容编号</th><th>状态</th></tr></thead>
                  <tbody>
                    {[...(cur.sections || [])]
                      .sort((a: any, b: any) =>
                        ["overview", "industry", "operations", "financials", "peer", "risk", "chain", "data_quality"].indexOf(a.section_key) -
                        ["overview", "industry", "operations", "financials", "peer", "risk", "chain", "data_quality"].indexOf(b.section_key))
                      .map((s: any) => (
                        <tr key={s.section_key}>
                          <td className="lab">{s.content.title}</td>
                          <td className="mono" style={{ fontSize: 10.5 }}>{s.content_hash.slice(0, 8)}</td>
                          <td>已发布</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                </div>
              ) : (
                <div className="empty">选择两个不同版本查看差异</div>
              )}

              <div className="panel tight" style={{ marginTop: 16, borderColor: "rgba(214,251,106,.18)" }}>
                <div className="panel-h"><h3>增量更新怎么保证「只动该动的」</h3></div>
                <div style={{ fontSize: 11.8, color: "var(--muted)", lineHeight: 2 }}>
                  ① 新材料先定位到原表单元格，确认属于哪个指标、哪一年；<br />
                  ② 与旧值逐项比对，标出真正改变的事实与判断；<br />
                  ③ 沿依赖关系找出受影响章节；<br />
                  ④ 只重写受影响章节，其余保持原版本；<br />
                  ⑤ 发布前校验基线版本，避免覆盖别人的更新。
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
