import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .add import add_item
from .exceptions import ExceptionsError
from .foundation import FoundationError, run_foundation
from .inbox import read_inbox
from .init import init_repo
from .onboard import run as onboard_run
from .query import query
from .scan import scan
from .sds_ready import run as sds_ready_run
from .triage import assign, file_inferred, item_repo, render_inbox, untriaged
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
    p.add_argument("--show", metavar="ID", help="print one item's full text")
    p.add_argument("--plain", action="store_true", help="one unshortened line per item")
    p.add_argument(
        "--file-inferred", action="store_true", help="file items into their inferred repos"
    )
    p.add_argument("--yes", action="store_true", help="with --file-inferred: write the changes")
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
    p = sub.add_parser("sds-ready")
    p.add_argument("repo")
    args = parser.parse_args(argv)

    if args.cmd == "onboard":
        return onboard_run(Path(args.repo))
    if args.cmd == "sds-ready":
        return sds_ready_run(Path(args.repo))

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
        modes = [m for m in ("assign", "show", "file_inferred", "plain") if getattr(args, m)]
        if len(modes) > 1:
            print("error: use only one of --assign, --show, --file-inferred, --plain")
            return 2
        if args.yes and not args.file_inferred:
            print("error: --yes only applies to --file-inferred")
            return 2
        if args.assign:
            if not args.repo:
                print("error: --assign requires --repo")
                return 2  # [debate-fix]
            assign(args.assign, Path(args.repo))
            print(f"assigned {args.assign}")
            return 0
        if args.show:
            item = next((i for i in read_inbox() if i.id == args.show), None)
            if item is None:
                print(f"error: no inbox item {args.show}")
                return 1
            print(f"{item.id}  {item.priority or '--'}  {item.ts[:10]}  {item.status}")
            print(f"repo: {item.inferred_repo or '(none inferred)'}\n\n{item.text}")
            return 0
        if args.file_inferred:
            result = file_inferred(apply=args.yes)
            verb = "filed" if args.yes else "would file"
            filed = Counter(str(item_repo(i)) for i in result.filed)
            skipped = Counter((str(item_repo(i)), why) for i, why in result.skipped)
            for repo, n in sorted(filed.items()):
                print(f"{verb} {n:>3}  {repo}")
            for (repo, why), n in sorted(skipped.items()):
                print(f"skipped {n:>3}  {repo}  ({why})")
            print(f"{len(result.filed)} {verb}, {len(result.skipped)} skipped.")
            if not args.yes and result.filed:
                print("Nothing written. Re-run with --yes to file them.")
            return 0
        if args.plain:
            for i in untriaged():
                print(f"{i.id}  conf={i.confidence}  {i.text}")
            return 0
        print(render_inbox(untriaged()))
        return 0
    if args.cmd == "scan":
        roots = [Path(r) for r in args.roots] if args.roots else None
        result = scan(roots=roots)
        print(json.dumps(result))
        # 3: the scan ran, but without the member record it measured no repository's
        # factory capability (integrations/portfolio-scan.sh passes it through).
        return 3 if result["member_record_unreadable"] else 0
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
