"""命令行：seed / run / ask / update / eval。

每个里程碑都能用一条命令复现，测试与演示不依赖前端。
"""

from __future__ import annotations

import argparse
import json

from .storage import repo
from .storage.db import init_db


def cmd_seed(args: argparse.Namespace) -> None:
    from .services.ingest import seed_corpus

    info = init_db()
    out = seed_corpus(force=args.force)
    print(f"db={info['path']} integrity={info['integrity']}")
    print(f"documents={out['documents']} ok={out['ok']}")
    for d in out["details"]:
        print(f"  {d.get('file','?'):<36} facts={d.get('facts',0):<4} pages={d.get('pages',0)} {d.get('status')}")


def cmd_run(args: argparse.Namespace) -> None:
    from .workflow.runner import execute

    req = {"entity_id": args.entity, "fiscal_years": [int(x) for x in args.years.split(",")],
           "as_of": args.as_of, "peer_ids": args.peers.split(",") if args.peers else [],
           "run_id": "cli-run"}
    repo.create_run({"run_id": "cli-run", "job_kind": "research", "report_id": None,
                     "status": "running", "idempotency_key": None, "budget": {}, "payload": req,
                     "result": {}, "error": None, "heartbeat_at": None, "created_at": None,
                     "finished_at": None}) if not repo.get_run("cli-run") else None
    out = execute(req, model_mode=args.model_mode, source_mode=args.source_mode)
    v = out.get("version")
    if not v:
        print("FAILED", out.get("errors"))
        return
    print(f"report={v['report_id']} version=v{v['version_no']} hash={v['content_hash'][:16]}")
    for s in v["sections"]:
        print(f"  {s['section_key']:<14} {s['content_hash'][:12]} {'reused' if s['reused'] else ''}")


def cmd_ask(args: argparse.Namespace) -> None:
    from .services import qa

    out = qa.answer(args.report, args.version, args.question)
    print(out["answer"])
    print("\n引用：", ", ".join(out["refs"][:6]))


def cmd_update(args: argparse.Namespace) -> None:
    from .services import update

    corr = next((d for d in repo.documents_visible() if d["source_type"] == "correction"), None)
    req = {"entity_id": args.entity, "fiscal_years": [int(x) for x in args.years.split(",")],
           "as_of": args.as_of, "peer_ids": args.peers.split(",") if args.peers else []}
    prev = update.preview(args.report, args.base, req, as_of=args.as_of,
                          staged=[corr["document_id"]] if corr and args.stage_correction else [])
    print("draft", prev["draft_version"], "changed_sections", prev["changed_sections"])
    print(json.dumps(prev["diff"]["counts"], ensure_ascii=False))
    for s in prev["diff"]["sections"]:
        print(f"  {s['section_key']:<14} {'CHANGED' if s['changed'] else 'same   '} "
              f"{s['old_hash']} -> {s['new_hash']} {'(same version id)' if s['same_version_id'] else ''}")
    for m in prev["diff"]["metrics"]:
        print(f"  metric {m['label']:<24} {m['year']} {m['old_display']} -> {m['new_display']}")
    if args.commit:
        res = update.commit(args.report, prev["draft_version"], args.base)
        print("commit:", json.dumps(res, ensure_ascii=False))


def cmd_eval(args: argparse.Namespace) -> None:
    from .eval.harness import run_eval

    report = run_eval()
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, indent=2))
    if args.verbose:
        print(json.dumps(report["details"], ensure_ascii=False, indent=1)[:4000])


def main() -> None:
    p = argparse.ArgumentParser(prog="evidence-chain")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="初始化数据库并载入演示语料")
    s.add_argument("--pack", default="beer-demo")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_seed)

    r = sub.add_parser("run", help="跑一次完整研究")
    r.add_argument("--entity", default="SH:600600")
    r.add_argument("--years", default="2023,2024,2025")
    r.add_argument("--as-of", default="2026-04-30")
    r.add_argument("--peers", default="SH:600132,SZ:002461")
    r.add_argument("--model-mode", default="mock")
    r.add_argument("--source-mode", default="replay")
    r.set_defaults(fn=cmd_run)

    a = sub.add_parser("ask", help="在指定版本内追问")
    a.add_argument("--report", default="rpt:SH:600600:2023-2025")
    a.add_argument("--version", type=int, default=1)
    a.add_argument("--question", required=True)
    a.set_defaults(fn=cmd_ask)

    u = sub.add_parser("update", help="补证预览 / 提交")
    u.add_argument("--report", default="rpt:SH:600600:2023-2025")
    u.add_argument("--base", type=int, default=1)
    u.add_argument("--entity", default="SH:600600")
    u.add_argument("--years", default="2023,2024,2025")
    u.add_argument("--as-of", default="2026-06-30")
    u.add_argument("--peers", default="SH:600132,SZ:002461")
    u.add_argument("--stage-correction", action="store_true")
    u.add_argument("--commit", action="store_true")
    u.set_defaults(fn=cmd_update)

    e = sub.add_parser("eval", help="跑金标评测")
    e.add_argument("--verbose", action="store_true")
    e.set_defaults(fn=cmd_eval)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
