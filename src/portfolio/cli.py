import argparse
import json
from datetime import datetime
from pathlib import Path

from .add import add_item
from .exceptions import ExceptionsError
from .foundation import FoundationError, run_foundation
from .init import init_repo
from .onboard import run as onboard_run
from .query import query
from .scan import scan
from .triage import assign, untriaged
from .validator import lint


def main(argv=None) -> int:  # noqa: C901
    parser = argparse.ArgumentParser(prog="portfolio")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("repo")
    p.add_argument("--tier", default="active")
    p = sub.add_parser("lint")
    p.add_argument("repo")
    p = sub.add_parser("add")
    p.add_argument("text", nargs="+")
    p.add_argument("--repo")
    p.add_argument("--priority")
    p = sub.add_parser("triage")
    p.add_argument("--assign")
    p.add_argument("--repo")
    p = sub.add_parser("scan")
    p.add_argument("--roots", nargs="*")
    p = sub.add_parser("foundation")
    p.add_argument("--roots", nargs="*")
    p = sub.add_parser("query")
    for flag in ("tier", "status", "tag"):
        p.add_argument(f"--{flag}")
    p.add_argument("--stale", action="store_true")
    p.add_argument("--has-backlog", action="store_true")
    p = sub.add_parser("onboard")
    p.add_argument("repo")
    args = parser.parse_args(argv)

    if args.cmd == "onboard":
        return onboard_run(Path(args.repo))

    if args.cmd == "init":
        print(f"initialized {init_repo(Path(args.repo), tier=args.tier).path}")
        return 0
    if args.cmd == "lint":
        findings = lint(Path(args.repo))
        for f in findings:
            print(f"{f.severity} {f.code}: {f.message}")
        return 1 if any(f.severity == "FAIL" for f in findings) else 0
    if args.cmd == "add":
        item = add_item(
            " ".join(args.text),
            repo=Path(args.repo) if args.repo else None,
            priority=args.priority,
            cwd=Path.cwd(),
            now_iso=datetime.now().isoformat(timespec="microseconds"),
        )
        print(f"captured [{item.status}] {item.id}: {item.text}")
        return 0
    if args.cmd == "triage":
        if args.assign:
            if not args.repo:
                print("error: --assign requires --repo")
                return 2  # [debate-fix]
            assign(args.assign, Path(args.repo))
            print(f"assigned {args.assign}")
            return 0
        for i in untriaged():
            print(f"{i.id}  conf={i.confidence}  {i.text}")
        return 0
    if args.cmd == "scan":
        roots = [Path(r) for r in args.roots] if args.roots else None
        print(json.dumps(scan(roots=roots)))
        return 0
    if args.cmd == "foundation":
        roots = [Path(r) for r in args.roots] if args.roots else None
        try:
            report = run_foundation(roots=roots)
        except (ExceptionsError, FoundationError) as e:
            print(f"error: {e}")
            return 2
        s = report["summary"]
        print(
            f"foundation: {len(report['repos'])} repos · violations={s['violation']} "
            f"accepted={s['accepted-exception']} unknown={s['unknown']}"
        )
        return report["exit_code"]
    if args.cmd == "query":
        filters = {
            k: v for k, v in (("tier", args.tier), ("status", args.status), ("tag", args.tag)) if v
        }
        if args.stale:
            filters["stale"] = True
        if args.has_backlog:
            filters["has_backlog"] = True
        for x in query(filters):
            print(f"{x['name']:24} {x.get('tier', '-'):8} {x.get('status', '-')}")
        return 0
    return 2
