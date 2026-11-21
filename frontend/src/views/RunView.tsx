import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import AgentFlow from "../components/AgentFlow";
import { ArrowUpRight, Check, File, Layers, Play, Shield, Spark } from "../components/icons";

const FALLBACK_AGENTS = [
  { id: "plan", name: "计划 Agent", code: "PLAN", stage: "规划", nodes: ["plan"], verb: "先看有什么", color: "#d6fb6a" },
  { id: "collect", name: "资料 Agent", code: "COLLECT", stage: "搜集", nodes: ["collect", "ingest"], verb: "只提查询提案", color: "#7fa6ff" },
  { id: "finance", name: "财务 Agent", code: "FINANCE", stage: "核验", nodes: ["finance_extract", "verify_calc"], verb: "只指认单元格", color: "#e8c583" },
  { id: "industry", name: "行业 Agent", code: "INDUSTRY", stage: "行业", nodes: ["industry", "validate_industry"], verb: "每条边有出处", color: "#9be6c4" },
  { id: "risk", name: "风险 Agent", code: "RISK", stage: "解释", nodes: ["risk_explain"], verb: "只解释已触发", color: "#ff7a6b" },
  { id: "audit", name: "审核 Agent", code: "AUDIT", stage: "审核", nodes: ["compose", "audit"], verb: "不改数字", color: "#b79cff" },
];

const NODE_LABEL: Record<string, string> = {
  plan: "覆盖矩阵", collect: "查询提案", ingest: "入库与定位",
  finance_extract: "候选单元格", verify_calc: "事实与指标",
  industry: "统计与图谱", validate_industry: "证据校验",
  build_ctx: "基准与规则", risk_explain: "解释与反证",
  compose: "模板与引用", audit: "校验与发布",
};

const NODE_DESC: Record<string, string> = {
  plan: "统计哪些字段在哪一年有原件",
  collect: "按缺口提查询词与预期发布方",
  ingest: "登记文档、单元格坐标与页码",
  finance_extract: "只指认单元格位置，不返回数字",
  verify_calc: "同键比较、冲突判定、逐项复算",
  industry: "行业事实 + 有证据的关系边",
  validate_industry: "点不开原文的边一律降级",
  build_ctx: "同业中位数 + 确定性规则",
  risk_explain: "只解释已触发警报",
  compose: "数字由证据绑定，不自行编造",
  audit: "引用可达 + 语义复检 + 版本发布",
};

function agentState(agent: any, stages: Record<string, string>) {
  const st = (agent.nodes || []).map((n: string) => stages[n]).filter(Boolean);
  if (!st.length) return "idle";
  if (st.includes("fail")) return "fail";
  if (st.includes("start")) return "active";
  if (st.filter((s) => s === "ok" || s === "skip").length === (agent.nodes || []).length) return "done";
  if (st.includes("ok")) return "active";
  return "pending";
}

const STATE_TEXT: Record<string, string> = {
  idle: "待运行", pending: "排队", active: "进行中", done: "已完成", fail: "失败",
};

const ROLE_LABEL: Record<string, string> = {
  plan: "计划", collect: "资料", finance_extract: "财务抽取",
  industry: "行业", risk_explain: "风险解释", audit: "审核",
};

export default function RunView({
  stages, log, running, onRun, form, setForm, entities, meta, onSeed, seeded, report, onRef, runInfo,
}: any) {
  const [llm, setLlm] = useState<any>(null);
  const [picked, setPicked] = useState("plan");
  const [showContract, setShowContract] = useState(true);

  useEffect(() => { api.llm().then(setLlm).catch(() => {}); }, []);

  const agents = meta?.agents?.agents || FALLBACK_AGENTS;
  const agent = agents.find((a: any) => a.id === picked) || agents[0];

  const overview = report?.sections?.find((s: any) => s.section_key === "overview")?.content;
  const riskSec = report?.sections?.find((s: any) => s.section_key === "risk")?.content;
  const dq = report?.sections?.find((s: any) => s.section_key === "data_quality")?.content;

  const doneCount = useMemo(
    () => Object.values(stages || {}).filter((s: any) => s === "ok").length,
    [stages],
  );
  const progress = Math.min(100, Math.round((doneCount / 11) * 100));

  const counts = useMemo(() => {
    const m: Record<string, string[]> = {};
    (log || []).forEach((l: any) => {
      if (l.counts) {
        m[l.node] = Object.entries(l.counts)
          .filter(([k]) => k !== "elapsed_ms")
          .map(([k, v]) => `${k} ${v}`);
      }
    });
    return m;
  }, [log]);

  const subject = entities.find((e: any) => e.entity_id === form.entity);

  const toggleYear = (y: number) => {
    const years = form.years.split(",").map((x: string) => x.trim()).filter(Boolean);
    const next = years.includes(String(y)) ? years.filter((x: string) => x !== String(y)) : [...years, String(y)];
    setForm({ ...form, years: next.sort().join(",") });
  };

  const selectedYears = form.years.split(",").map((x: string) => x.trim());

  return (
    <div className="view-enter studio">
      <div className="page-head studio-head">
        <div>
          <div className="kicker">Multi-agent research desk</div>
          <h2>多智能体研究台</h2>
          <p className="sub">
            六个角色分工明确、权限受限：计划定范围，资料找原件，财务核口径，行业连关系，风险做解释，审核守发布。
          </p>
        </div>
        <div className="spacer" />
        <span className="badge-mode"><span className={"dot " + form.sourceMode} />来源 <b>{form.sourceMode === "replay" ? "缓存回放" : form.sourceMode === "cached" ? "本地缓存" : "在线抓取"}</b></span>
        <span className="badge-mode"><span className={"dot " + form.modelMode} />模型 <b>{form.modelMode === "live" ? "大模型" : "受控模板"}</b></span>
        <button className="btn primary" onClick={onRun} disabled={running || !seeded}>
          {running ? `研究中 · ${progress}%` : <><Play size={12} /> 运行研究</>}
        </button>
      </div>

      <div className="studio-grid">
        <aside className="studio-side">
          <div className="panel">
            <div className="panel-h"><h3>研究任务</h3><span className="hint">可重复执行</span></div>
            <div className="field">
              <label>研究主体</label>
              <select value={form.entity} onChange={(e) => setForm({ ...form, entity: e.target.value })}>
                {(entities || []).map((e: any) => (
                  <option key={e.entity_id} value={e.entity_id}>
                    {e.name}（{e.ticker}）
                  </option>
                ))}
              </select>
              {subject && (
                <div className="studio-subject">
                  <span className="ss-dot" />
                  <b>{subject.name}</b>
                  <span className="mono">{subject.entity_id}</span>
                  <span className="ss-role">{subject.role === "subject" ? "研究主体" : "样本成员"}</span>
                </div>
              )}
            </div>
            <div className="field">
              <label>财年</label>
              <div className="year-row">
                {[2023, 2024, 2025].map((y) => (
                  <button
                    key={y}
                    className={"year-chip" + (selectedYears.includes(String(y)) ? " on" : "")}
                    onClick={() => toggleYear(y)}
                  >FY{y}</button>
                ))}
                <input
                  className="year-input" type="text" value={form.years}
                  onChange={(e) => setForm({ ...form, years: e.target.value })}
                />
              </div>
            </div>
            <div className="field">
              <label>观察截止日</label>
              <input type="text" value={form.asOf} onChange={(e) => setForm({ ...form, asOf: e.target.value })} />
              <div className="field-hint">晚于该日披露的材料不参与本次研究。</div>
            </div>
            <div className="field">
              <label>数据来源</label>
              <div className="seg">
                {[["replay", "缓存回放"], ["cached", "本地缓存"], ["live", "在线抓取"]].map(([m, label]) => (
                  <button key={m} className={form.sourceMode === m ? "on" : ""} onClick={() => setForm({ ...form, sourceMode: m })}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="field-hint">
                {form.sourceMode === "replay" ? "使用已保存的原件与结果，断网也能演示；核心数字仍可复算。"
                  : form.sourceMode === "cached" ? "读取本地已下载的原件，不新增网络请求。"
                    : "在线获取公开材料；遇到接口失败时回落到本地缓存。"}
              </div>
            </div>
            <div className="field">
              <label>生成方式</label>
              <div className="seg">
                {[["mock", "受控模板"], ["live", "大模型"]].map(([m, label]) => (
                  <button key={m} className={form.modelMode === m ? "on" : ""} onClick={() => setForm({ ...form, modelMode: m })}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="llm-hint">
                {llm?.configured ? (
                  <><i className="on" />已启用大模型辅助（{llm.model}）</>
                ) : (
                  <><i />未启用大模型；系统仍会按确定性规则完成研究。</>
                )}
              </div>
            </div>
            <button className="btn primary wide" disabled={running} onClick={onRun}>
              {running ? "研究中…" : <><Play size={12} /> 运行研究</>}
            </button>
            {!seeded && <button className="btn ghost wide" onClick={onSeed} style={{ marginTop: 8 }}>载入演示语料</button>}
            <div className="note tight-note" style={{ marginBottom: 0 }}>
              数据来源与生成方式分别标注，不合并成一个状态灯。
            </div>
          </div>

          <div className="panel">
            <div className="panel-h"><h3>角色契约</h3><span className="hint">不是提示词，是边界</span></div>
            <div className="contract-pick">
              {agents.map((a: any) => (
                <button
                  key={a.id}
                  className={"cp-dot" + (picked === a.id ? " on" : "")}
                  style={{ ["--c" as any]: a.color }}
                  onClick={() => { setPicked(a.id); setShowContract(true); }}
                  title={a.name}
                />
              ))}
              <span className="spacer" />
              <button className="cp-toggle" onClick={() => setShowContract((v) => !v)}>
                {showContract ? "收起" : "展开"}
              </button>
            </div>
            {showContract && (
              <div className="contract">
                <div className="contract-h">
                  <span className="contract-code" style={{ color: agent.color }}>{agent.code}</span>
                  <b>{agent.name}</b>
                </div>
                <p>{agent.mission}</p>
                <div className="contract-row"><span>输入</span><div>{(agent.inputs || []).map((x: string) => <i key={x}>{x}</i>)}</div></div>
                <div className="contract-row"><span>输出</span><div>{(agent.outputs || []).map((x: string) => <i key={x}>{x}</i>)}</div></div>
                <div className="contract-row"><span>可访问</span><div>{(agent.tools || []).map((x: string) => <i key={x}>{x}</i>)}</div></div>
                <div className="contract-row forbid"><span>禁止</span><div>{(agent.forbidden || []).map((x: string) => <i key={x}>{x}</i>)}</div></div>
                <div className="contract-guard">{agent.guard}</div>
              </div>
            )}
          </div>
        </aside>

        <main className="studio-main">
          <div className="panel agent-panel">
            <div className="panel-h">
              <h3>协作调度</h3>
              <span className="hint">资料 / 财务 / 行业并行，风险解释后统一审核发布</span>
              <span className="spacer" />
              <span className={"pill " + (running ? "WARN" : doneCount ? "HIGH" : "")}>
                {running ? "运行中" : doneCount ? "本轮已完成" : "待运行"}
              </span>
            </div>
            <AgentFlow agents={agents} stages={stages} onPick={setPicked} picked={picked} height={286} />
            <div className="agent-cards">
              {agents.map((a: any) => {
                const st = agentState(a, stages || {});
                const c = a.nodes.flatMap((n: string) => counts[n] || []);
                return (
                  <button
                    key={a.id}
                    className={"agent-card " + st + (picked === a.id ? " on" : "")}
                    onClick={() => { setPicked(a.id); setShowContract(true); }}
                    style={{ ["--c" as any]: a.color }}
                  >
                    <div className="ac-top">
                      <span className="ac-code">{a.code}</span>
                      <span className={"ac-state " + st}>{STATE_TEXT[st]}</span>
                    </div>
                    <div className="ac-name">{a.stage}</div>
                    <div className="ac-verb">{a.verb}</div>
                    <div className="ac-out mono">{c.slice(0, 2).join(" · ") || (st === "done" ? "已产出" : "—")}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="studio-row">
            <div className="panel event-panel">
              <div className="panel-h">
                <h3>事件流</h3>
                <span className="hint">实时进度 · 断线可续</span>
                <span className="spacer" />
                <span className="mono" style={{ fontSize: 10, color: "var(--dim)" }}>{doneCount}/11 节点</span>
              </div>
              <div className="log studio-log">
                {(log || []).slice(-60).map((l: any, i: number) => (
                  <div key={i}>
                    <span className="t">{l.ts?.slice(11, 19) || ""}</span>
                    <span className={"node-tag"}>{l.node}</span>
                    <span className={l.status === "ok" ? "ok" : l.status === "fail" ? "fail" : ""}>
                      {l.message}
                    </span>
                  </div>
                ))}
                {(!log || log.length === 0) && (
                  <div className="log-empty">
                    <b>等待运行</b>
                    <span>点击「运行研究」，11 个节点的决策、计数与耗时将在此实时输出。</span>
                  </div>
                )}
              </div>
            </div>

            <div className="panel output-panel">
              <div className="panel-h">
                <h3>本轮产出</h3>
                <span className="hint">{report ? `v${report.version.version_no} · ${report.version.as_of}` : "尚未发布"}</span>
              </div>
              {!report && <div className="empty small">运行一次研究后，这里会出现指标、风险与章节摘要。</div>}
              {report && (
                <>
                  <div className="output-kpis">
                    {(overview?.kpis || []).slice(0, 4).map((k: any, i: number) => (
                      <button className="output-kpi" key={i} onClick={() => k.ref && onRef?.(k.ref)}>
                        <span>{k.label}</span>
                        <b>{k.value || "缺证"}</b>
                        <em>{k.status === "OK" ? k.confidence : k.status}</em>
                      </button>
                    ))}
                  </div>
                  <div className="risk-matrix">
                    {(riskSec?.rules || []).map((r: any) => (
                      <div className={"rm-row " + r.status} key={r.rule_id}>
                        <span className="rm-dot" />
                        <span className="rm-label">{r.label}</span>
                        <span className="rm-status">{r.status === "TRIGGERED" ? "触发" : r.status === "NOT_EVALUABLE" ? "不可评估" : "未触发"}</span>
                      </div>
                    ))}
                  </div>
                  <div className="output-meta">
                    <span><File size={11} /> {(dq?.coverage || []).map((c: any) => `${c.value}${c.unit}${c.label}`).join(" · ")}</span>
                    <span className="mono">报告编号 {report.version.content_hash.slice(0, 12)}</span>
                  </div>
                  <div className="section-fingerprint">
                    {[...(report.sections || [])].map((s: any) => (
                      <div className="sf-row" key={s.section_key}>
                        <span>{s.content.title}</span>
                        <i style={{ width: `${Math.max(8, Math.min(100, (s.content.paragraphs || []).length * 14))}%` }} />
                        <em className="mono">{s.content.paragraphs.length} 段</em>
                      </div>
                    ))}
                  </div>
                  {runInfo?.agent_log?.length > 0 && (
                    <div className="agent-trace">
                      <div className="at-head">
                        <b>Agent 协作记录</b>
                        <span>
                          {runInfo.llm_usage?.calls
                            ? `${runInfo.llm_usage.calls} 次模型调用 · ${(runInfo.llm_usage.prompt_tokens + runInfo.llm_usage.completion_tokens).toLocaleString()} tokens`
                            : "确定性策略 · 0 次模型调用"}
                        </span>
                      </div>
                      {runInfo.agent_log.map((a: any) => (
                        <div className="at-row" key={a.role}>
                          <b>{ROLE_LABEL[a.role] || a.role}</b>
                          <span>{a.mode === "live" ? "大模型" : "确定性策略"}</span>
                          <em className={a.used_fallback ? "warn" : "ok"}>
                            {a.used_fallback ? "回落模板" : "通过校验"}
                          </em>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <div className="panel pipeline-panel">
            <div className="panel-h">
              <h3>节点与依赖</h3>
              <span className="hint">图只调度；业务数值始终留在同一条证据链里</span>
              <span className="spacer" />
              <span className="pill">{meta?.pipeline?.nodes?.length || 11} 节点</span>
            </div>
            <div className="pipeline-list">
              {(meta?.pipeline?.nodes || []).map((n: any) => (
                <div className={"pipe-node" + (stages?.[n.name] === "ok" ? " done" : stages?.[n.name] === "start" ? " run" : "")} key={n.name}>
                  <span className="pn-name">{NODE_LABEL[n.name] || n.label}</span>
                  <span className="pn-desc">{NODE_DESC[n.name] || n.name}</span>
                  <span className="pn-dep mono">{(n.deps || []).join(" · ") || "entry"}</span>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
