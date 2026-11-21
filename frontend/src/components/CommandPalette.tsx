import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ArrowUpRight, Close, Search } from "./icons";

type Action = { kind: string; label: string; target: string; __entity?: any };

export default function CommandPalette({
  open,
  onClose,
  onNavigate,
  onPickEntity,
  onAsk,
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (tab: string, section?: string) => void;
  onPickEntity: (entityId: string, name: string) => void;
  onAsk: (question: string) => void;
}) {
  const [q, setQ] = useState("");
  const [data, setData] = useState<any>(null);
  const [idx, setIdx] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setIdx(0);
    setTimeout(() => input.current?.focus(), 30);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const t = setTimeout(() => {
      api.search(q).then((r) => alive && setData(r)).catch(() => alive && setData(null));
    }, 120);
    return () => { alive = false; clearTimeout(t); };
  }, [q, open]);

  const actions: Action[] = [];
  (data?.actions || []).forEach((a: any) => actions.push(a));
  (data?.entities || []).forEach((e: any) => actions.push({
    kind: "entity", label: `研究 · ${e.name}（${e.ticker}）`, target: e.entity_id, __entity: e,
  }));
  (data?.industries || []).forEach((i: any) => actions.push({
    kind: "industry", label: `行业 · ${i.name}`, target: i.id,
  }));

  const run = (a: Action) => {
    if (a.kind === "entity" && a.__entity) {
      onPickEntity(a.__entity.entity_id, a.__entity.name);
    } else if (a.kind === "industry") {
      onNavigate("industry");
    } else if (a.kind === "eval") {
      onNavigate("eval");
    } else if (a.kind === "run") {
      onNavigate("run");
    } else if (a.kind === "report") {
      onNavigate("report", a.target);
    } else if (a.kind === "ask") {
      const e = (data?.entities || []).find((x: any) => x.entity_id === a.target);
      onAsk(`${e?.name || ""} 2025 年毛利率是多少？`);
    }
    onClose();
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, actions.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
      if (e.key === "Enter" && actions[idx]) { e.preventDefault(); run(actions[idx]); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, actions, idx]);

  if (!open) return null;

  const group = (kind: string) => actions.filter((a) => a.kind === kind);
  const entityActions = group("entity");
  const industryActions = group("industry");
  const otherActions = actions.filter((a) => !["entity", "industry"].includes(a.kind));

  return (
    <div className="cmdk-mask" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cmdk">
        <div className="cmdk-in">
          <Search size={15} />
          <input
            ref={input}
            value={q}
            onChange={(e) => { setQ(e.target.value); setIdx(0); }}
            placeholder="搜索公司、行业，或直接输入问题…"
          />
          <button className="cmdk-esc" onClick={onClose}><Close size={12} />ESC</button>
        </div>
        <div className="cmdk-body">
          {!q && (
            <div className="cmdk-tip">
              输入公司名或代码（如「美的」「600600」），也可以直接问「比较啤酒和白酒的毛利率」。
            </div>
          )}
          {industryActions.length > 0 && <div className="cmdk-grp">行业</div>}
          {industryActions.map((a) => (
            <button key={a.target} className="cmdk-item" onClick={() => run(a)}>
              <span className="k">行业</span><span>{a.label}</span><ArrowUpRight size={12} />
            </button>
          ))}
          {entityActions.length > 0 && <div className="cmdk-grp">公司</div>}
          {entityActions.map((a) => (
            <button key={a.target} className="cmdk-item" onClick={() => run(a)}>
              <span className="k">公司</span><span>{a.label}</span><ArrowUpRight size={12} />
            </button>
          ))}
          {otherActions.length > 0 && <div className="cmdk-grp">动作</div>}
          {otherActions.map((a) => (
            <button key={a.label} className="cmdk-item" onClick={() => run(a)}>
              <span className="k">动作</span><span>{a.label}</span><ArrowUpRight size={12} />
            </button>
          ))}
          {q && data && !actions.length && (
            <button className="cmdk-item" onClick={() => { onAsk(q); onClose(); }}>
              <span className="k">追问</span><span>在报告里追问「{q}」</span><ArrowUpRight size={12} />
            </button>
          )}
        </div>
        <div className="cmdk-foot">
          <span>↑↓ 选择</span><span>↵ 打开</span><span>esc 关闭</span>
          <span className="spacer" />
          <span>只检索预置样本；未收录的公司不生成假报告</span>
        </div>
      </div>
    </div>
  );
}
