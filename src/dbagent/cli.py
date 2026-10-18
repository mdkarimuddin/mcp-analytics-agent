"""Command line: build demo data, ask the agent, and review proposed changes (human-only)."""

from __future__ import annotations

import argparse
import asyncio
import json

from . import db, demo_data, tools


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dbagent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="build the synthetic demo database")
    sub.add_parser("pending", help="list proposed changes")
    for name in ("approve", "reject", "restore"):
        s = sub.add_parser(name, help=f"{name} a proposal (human only)")
        s.add_argument("proposal_id", type=int)
    s = sub.add_parser("ask", help="ask the agent (needs ANTHROPIC_API_KEY)")
    s.add_argument("question")
    args = p.parse_args(argv)

    if args.cmd == "demo":
        print(f"built {demo_data.build(db.data_path())}")
    elif args.cmd == "pending":
        for r in tools.list_pending():
            print(f"#{r['id']} ({r['preview_rows']} rows) {r['sql']}  -- {r['reason']}")
    elif args.cmd in ("approve", "reject", "restore"):
        fn = {"approve": tools.approve, "reject": tools.reject, "restore": tools.restore}[args.cmd]
        print(json.dumps(fn(args.proposal_id)))
    elif args.cmd == "ask":
        from .agent import ask_with_mcp, require_api_key

        problem = require_api_key()
        if problem:
            raise SystemExit(problem)
        res = asyncio.run(ask_with_mcp(args.question))
        print(res.answer)
        print(f"\n[steps={res.steps} tools={[c['name'] for c in res.tool_calls]} "
              f"tokens={res.input_tokens + res.output_tokens}]")


if __name__ == "__main__":
    main()
