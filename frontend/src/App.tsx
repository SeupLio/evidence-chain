import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamRun } from "./api";
import CommandPalette from "./components/CommandPalette";
import EvidenceDrawer from "./components/EvidenceDrawer";
import Landing from "./components/Landing";
import ThemeToggle from "./components/ThemeToggle";
import { ArrowUpRight, Check, Command, Mark, Pin, Play, Search } from "./components/icons";
import RunView from "./views/RunView";
import ReportView from "./views/ReportView";
import ProvenanceView from "./views/ProvenanceView";
import VersionsView from "./views/VersionsView";
import EvalView from "./views/EvalView";
import IndustryView from "./views/IndustryView";

const TABS = [
  ["run", "研究台"],
  ["report", "报告"],
  ["provenance", "证据地图"],
  ["industry", "行业"],
  ["versions", "版本与补证"],
  ["eval", "评测"],
];

const PEERS_BY_INDUSTRY: Record<string, string[]> = {
  beer: ["SH:600132", "SZ:002461"],
  baijiu: ["SZ:000858", "SZ:000568"],
  dairy: ["SH:600597", "SZ:002946"],
  appliance: ["SZ:000651", "SH:600690"],
  auto: ["SZ:601633", "SH:600104"],
  solar: ["SH:600438", "SZ:300274"],
};

const SOURCE_LABEL: Record<string, string> = {
  replay: "缓存回放", cached: "本地缓存", live: "在线抓取",
};
const MODEL_LABEL: Record<string, string> = {
  mock: "受控模板", live: "大模型",
};

export default function App() {
  const [tab, setTab] = useState(() => {
    const h = (location.hash || "").replace(/^#/, "");
    return h.split("&")[0] || "home";
  });
  const [meta, setMeta] = useState<any>(null);
  const [overview, setOverview] = useState<any>(null);
  const [entities, setEntities] = useState<any[]>([]);
  const [form, setForm] = useState({
    entity: "SH:600600", asOf: "2026-06-30", years: "2023,2024,2025",
    sourceMode: "replay", modelMode: "mock",
  });
  const [stages, setStages] = useState<Record<string, string>>({});
  const [log, setLog] = useState<any[]>([]);
  const [running, setRunning] = useState(false);
  const [reportId, setReportId] = useState<string | null>(null);
  const [versionNo, setVersionNo] = useState<number | null>(null);
  const [report, setReport] = useState<any>(null);
  const [runInfo, setRunInfo] = useState<any>(null);
  const [reportList, setReportList] = useState<any[]>([]);
  const [refId, setRefId] = useState<string | null>(() => {
    const m = (location.hash || "").match(/ref=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  });
  const [seeded, setSeeded] = useState(false);
  const [industries, setIndustries] = useState<any[]>([]);
  const [industryTab, setIndustryTab] = useState("beer");
  const [toast, setToast] = useState<string | null>(null);
  const [cmdk, setCmdk] = useState(false);
  const [askSeed, setAskSeed] = useState<{ q: string; n: number } | null>(null);
  const closeStream = useRef<null | (() => void)>(null);

  useEffect(() => {
    const onHash = () => {
      const h = (location.hash || "#home").replace(/^#/, "");
      setTab(h.split("&")[0] || "home");
      const m = location.hash.match(/ref=([^&]+)/);
      setRefId(m ? decodeURIComponent(m[1]) : null);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (k: string) => {
    location.hash = k;
    setTab(k);
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
    setRefId(null);
  };

  useEffect(() => {
    api.health().then((h) => setSeeded((h.tables || []).includes("facts"))).catch(() => {});
    api.industries().then((r) => setIndustries(r.industries || [])).catch(() => {});
    api.meta().then(setMeta).catch(() => {});
    api.overview().then(setOverview).catch(() => {});
    api.entities().then((r) => setEntities(r.candidates || [])).catch(() => {});
    api.reports().then((r) => {
      const list = r.reports || [];
      setReportList(list);
      // 默认打开青岛啤酒；有多份报告时由顶栏切换，避免首页主体与报告数据错位。
      const first = list.find((x: any) => x.report_id.includes("SH:600600")) || list[0];
      if (first) {
        setReportId(first.report_id);
        setVersionNo(first.head_version_no);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5200);
    return () => clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdk((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loadReport = useCallback((rid: string, v: number) => {
    api.version(rid, v).then((r) => {
      setReport(r);
      setVersionNo(v);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (reportId && versionNo) loadReport(reportId, versionNo);
  }, [reportId, versionNo, loadReport]);

  const onSeed = async () => {
    setToast("正在载入合成回归语料…");
    try {
      const r = await api.seed();
      if (r.error) { setToast(r.message || "当前库已含真实数据，拒绝混入合成语料"); return; }
      setSeeded(true);
      setToast(`已入库 ${r.ok}/${r.documents} 份原件（合成回归语料）`);
      const ents = await api.entities();
      setEntities(ents.candidates || []);
    } catch (e: any) {
      setToast(String(e.message || e));
    }
  };

  const onRun = async () => {
    setRunning(true);
    setStages({});
    setLog([]);
    go("run");
    try {
      const body = {
        entity_id: form.entity,
        fiscal_years: form.years.split(",").map((x) => Number(x.trim())).filter(Boolean),
        as_of: form.asOf,
        peer_ids: peersFor(form.entity),
        source_mode: form.sourceMode,
        model_mode: form.modelMode,
      };
      const r = await api.createRun(body);
      const rid = r.run_id;
      closeStream.current?.();
      closeStream.current = streamRun(
        rid,
        (e) => {
          if (e.node === "__run__") return;
          setStages((s) => ({ ...s, [e.node]: e.status }));
          setLog((l) => [...l, e]);
        },
        async (e) => {
          setRunning(false);
          setRunInfo(e.result || null);
          const v = e.result?.version;
          if (v) {
            setReportId(v.report_id);
            setVersionNo(v.version_no);
            setOverview(null);
            api.overview().then(setOverview).catch(() => {});
            go("report");
            setToast(`v${v.version_no} 已发布 · ${v.reused_sections?.length || 0} 个章节复用旧版本`);
          } else {
            setToast("任务未完成，请查看事件流");
          }
        },
      );
    } catch (e: any) {
      setRunning(false);
      setToast(String(e.message || e));
    }
  };

  useEffect(() => () => closeStream.current?.(), []);

  const subject = entities.find((e) => e.entity_id === form.entity) || entities[0];
  const reportSubject = reportId
    ? entities.find((e) => reportId.includes(e.entity_id))
    : null;
  const peersFor = (entityId: string) => {
    const ent = entities.find((e) => e.entity_id === entityId);
    const list = PEERS_BY_INDUSTRY[ent?.industry_id] || [];
    return list.filter((x) => x !== entityId);
  };

  const onNavigate = (t: string, section?: string) => {
    go(t);
    if (section) {
      setTimeout(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" }), 160);
    }
  };

  if (tab === "home") {
    return (
      <>
        <Landing
          onEnter={() => go("run")}
          onOpenReport={() => go("report")}
          onOpenIndustry={(id) => { setIndustryTab(id); go("industry"); }}
          onOpenProvenance={() => go("provenance")}
          report={report}
          subject={reportSubject || subject}
          overview={overview}
          reportId={reportId}
          versionNo={versionNo}
          onAsk={(q) => { setAskSeed({ q, n: Date.now() }); go("report"); }}
        />
        <CommandPalette
          open={cmdk} onClose={() => setCmdk(false)} onNavigate={onNavigate}
          onPickEntity={(id, name) => {
            setForm((f) => ({ ...f, entity: id }));
            go("run");
            setToast(`已切换研究主体：${name}`);
          }}
          onAsk={(q) => { setAskSeed({ q, n: Date.now() }); go("report"); }}
        />
        {toast && <Toast text={toast} onClose={() => setToast(null)} />}
      </>
    );
  }

  return (
    <div className="app">
      {running && <div className="top-progress" />}

      <div className="app-top">
        <button className="brand-btn" onClick={() => go("home")} title="返回首页">
          <span className="logo-mark"><Mark /></span>
          <span className="brand-txt">
            <b>经营证据链</b>
            <i>Evident</i>
          </span>
        </button>

        <div className="tabs">
          {TABS.map(([k, l]) => (
            <button key={k} className={"tab" + (tab === k ? " on" : "")} onClick={() => go(k)}>{l}</button>
          ))}
        </div>

        <div className="spacer" />

        <button className="cmdk-trigger" onClick={() => setCmdk(true)}>
          <Search size={12} />
          <span>搜索公司 / 追问</span>
          <kbd><Command size={9} />K</kbd>
        </button>

        {reportList.length > 1 && (
          <select
            className="report-switch"
            value={reportId || ""}
            onChange={(e) => {
              const item = reportList.find((x) => x.report_id === e.target.value);
              if (!item) return;
              setReportId(item.report_id);
              setVersionNo(item.head_version_no);
              setReport(null);
              go("report");
              setToast(`已切换报告：${entities.find((x) => x.entity_id === item.entity_id)?.name || item.entity_id}`);
            }}
            title="切换已发布报告"
          >
            {reportList.map((r) => (
              <option key={r.report_id} value={r.report_id}>
                {entities.find((e) => e.entity_id === r.entity_id)?.name || r.entity_id} · v{r.head_version_no}
              </option>
            ))}
          </select>
        )}

        <span className="badge-mode hide-sm"><span className={"dot " + form.sourceMode} />来源 <b>{SOURCE_LABEL[form.sourceMode] || form.sourceMode}</b></span>
        <span className="badge-mode hide-sm"><span className={"dot " + form.modelMode} />方式 <b>{MODEL_LABEL[form.modelMode] || form.modelMode}</b></span>
        {report && (
          <span className="badge-mode hide-sm">版本 <b>v{report.version.version_no}</b> · 截止 <b>{report.version.as_of}</b></span>
        )}
        <ThemeToggle className="hide-sm compact" />
        <button className="btn primary sm" onClick={onRun} disabled={running || !seeded}>
          {running ? "研究中…" : <><Play size={11} /> 运行研究</>}
        </button>
      </div>

      <div className="wrap">
        {tab === "run" && (
          <RunView
            stages={stages} log={log} running={running} onRun={onRun}
            form={form} setForm={setForm} entities={entities} meta={meta}
            onSeed={onSeed} seeded={seeded} report={report} onRef={setRefId}
            runInfo={runInfo}
          />
        )}
        {tab === "report" && (
          report ? (
            <div className="view-enter">
              <ReportView
                data={report}
                subject={reportSubject || subject}
                onRef={setRefId}
                onOpenProvenance={() => go("provenance")}
                right={
                  <AskPanel
                    reportId={reportId!}
                    versionNo={report.version.version_no}
                    onRef={setRefId}
                    seed={askSeed}
                  />
                }
              />
            </div>
          ) : <div className="empty">还没有报告。先在「研究台」运行一次。</div>
        )}
        {tab === "provenance" && (
          <ProvenanceView reportId={reportId} versionNo={versionNo} onRef={setRefId} />
        )}
        {tab === "versions" && (
          <VersionsView
            reportId={reportId}
            head={versionNo}
            onHeadChange={(v: number) => { setVersionNo(v); }}
          />
        )}
        {tab === "industry" && (
          <div className="view-enter">
            <IndustryView
              initial={industryTab}
              industries={industries}
              onPickSubject={(eid) => {
                setForm((f) => ({ ...f, entity: eid, asOf: "2026-06-30" }));
                go("run");
                setToast("已切换研究主体，运行研究即可生成该公司的报告");
              }}
            />
          </div>
        )}
        {tab === "eval" && <EvalView onRef={setRefId} />}
      </div>

      <CommandPalette
        open={cmdk} onClose={() => setCmdk(false)} onNavigate={onNavigate}
        onPickEntity={(id, name) => {
          setForm((f) => ({ ...f, entity: id }));
          go("run");
          setToast(`已切换研究主体：${name}`);
        }}
        onAsk={(q) => { setAskSeed({ q, n: Date.now() }); go("report"); }}
      />

      {refId && (
        <EvidenceDrawer refId={refId} onClose={() => setRefId(null)} onJump={(r) => setRefId(r)} />
      )}
      {toast && <Toast text={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

function Toast({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div className="toast">
      <span className="toast-dot" />
      <span style={{ flex: 1 }}>{text}</span>
      <button className="btn ghost sm" style={{ padding: "3px 10px", borderRadius: 999 }} onClick={onClose}>
        <Check size={11} /> 知道了
      </button>
    </div>
  );
}

type Turn = { q: string; a: any };

function AskPanel({
  reportId, versionNo, onRef, seed,
}: {
  reportId: string; versionNo: number;
  onRef: (r: string) => void;
  seed?: { q: string; n: number } | null;
}) {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [sugs, setSugs] = useState<string[]>([]);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.suggest(reportId, versionNo).then((r) => setSugs(r.suggestions || [])).catch(() => setSugs([]));
  }, [reportId, versionNo]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setQ(question);
    const history = turns.map((t) => t.q);
    try {
      const r = await api.ask(reportId, versionNo, question, history);
      setTurns((h) => [...h, { q: question, a: r }]);
      setQ("");
    } catch (e: any) {
      setTurns((h) => [...h, { q: question, a: { answer: String(e.message || e), refs: [], sources: [] } }]);
    } finally {
      setBusy(false);
      setTimeout(() => box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" }), 60);
    }
  };

  useEffect(() => {
    if (seed?.q) ask(seed.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.n]);

  return (
    <div className="ask-card">
      <div className="ask-head">
        <h3>追问</h3>
        <span className="ver"><Pin size={10} /> 钉住 v{versionNo}</span>
        <span className="spacer" />
        {turns.length > 0 && (
          <button className="ask-clear" onClick={() => setTurns([])}>新对话</button>
        )}
      </div>
      <div className="ask-box-ref">
        只检索该冻结版本的证据；第三方数据单独标注，不与年报原件混用。
      </div>

      <div className="ask-turns" ref={box}>
        {turns.length === 0 && (
          <div className="ask-welcome">
            <div className="aw-title">问这份报告里的任何数字</div>
            <div className="aw-sub">支持多轮：先问「美的 2024 年毛利率」，再问「为什么下降」。</div>
            <div className="aw-list">
              {(sugs.length ? sugs : [
                "毛利率在同行里处于什么位置？",
                "为什么经营现金流和净利润不同步？",
                "哪些资料没拿到，会影响哪个结论？",
                "讲一下这个行业的产业链上下游",
              ]).slice(0, 4).map((s) => (
                <button key={s} className="aw-chip" onClick={() => ask(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div className="turn" key={i}>
            <div className="turn-q">{t.q}</div>
            {t.a.inherited?.length > 0 && (
              <div className="turn-inherit">{t.a.inherited.join("；")}</div>
            )}
            {t.a.premise && (
              <div className="turn-premise">
                前提校验：问题说的是{t.a.premise.claimed === "down" ? "下降" : "上升"}，
                实际为{t.a.premise.actual === "up" ? "上升" : "下降"} {t.a.premise.change}{t.a.premise.unit}
              </div>
            )}
            {t.a.parsed && (t.a.parsed.entities?.length > 0 || t.a.parsed.year || t.a.parsed.metrics?.length > 0) && (
              <div className="parse-row">
                {t.a.parsed.entities?.map((e: string) => <span className="parse-tag" key={e}>{e}</span>)}
                {t.a.parsed.year && <span className="parse-tag">FY{t.a.parsed.year}</span>}
                {t.a.parsed.metrics?.length > 0 && <span className="parse-tag">{t.a.parsed.metrics.join(" / ")}</span>}
              </div>
            )}
            <div className="turn-a">
              {String(t.a.answer || "").split("\n").map((l: string, j: number) => <p key={j}>{l}</p>)}
            </div>
            {t.a.refs?.length > 0 && (
              <div className="chips">
                {t.a.refs.map((r: string, ri: number) => (
                  <span className="chip" key={r} onClick={() => onRef(r)}>
                    <span className="k">依据</span>{ri + 1}
                  </span>
                ))}
              </div>
            )}
            {t.a.sources?.length > 0 && (
              <div className="src-list">
                {t.a.sources.map((s: any) => (
                  <a className="src-item" key={s.url} href={s.url} target="_blank" rel="noreferrer">
                    <span className="k">外部</span>
                    <span style={{ flex: 1 }}>{s.title}</span>
                    <ArrowUpRight size={11} />
                  </a>
                ))}
              </div>
            )}
            {t.a.followups?.length > 0 && i === turns.length - 1 && (
              <div className="followups">
                {t.a.followups.slice(0, 3).map((f: string) => (
                  <span className="chip" key={f} onClick={() => ask(f)}>{f}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="turn busy"><span /><span /><span /></div>}
      </div>

      <div className="askbox">
        <input
          type="text"
          placeholder="问任意问题，支持多轮…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(q)}
        />
        <button className="btn primary" disabled={busy} onClick={() => ask(q)}>{busy ? "…" : "问"}</button>
      </div>
      <div className="ask-foot">
        <span>回答不修改报告</span>
        <span>·</span>
        <span>每条引用可点开原页</span>
      </div>
    </div>
  );
}
