"""Execution-based evaluation with the real model. Usage:
    export ANTHROPIC_API_KEY=...   (your own shell, never in a file)
    python eval/run_eval.py --trials 3
Each trial uses a fresh copy of the generated demo database, so real data is never touched.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dbagent import agent, demo_data
from dbagent.evalscore import score_case


def scalar(path: Path, sql: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1)
    args = ap.parse_args()
    problem = agent.require_api_key()
    if problem:
        print(problem)
        return 2
    cases = yaml.safe_load((ROOT / "eval" / "cases.yaml").read_text())["cases"]
    with tempfile.TemporaryDirectory() as tmp:
        master = demo_data.build(Path(tmp) / "master.db")
        results, unsafe, tokens = [], 0, 0
        for case in cases:
            truth = scalar(master, case["truth_sql"]) if "truth_sql" in case else None
            passes, notes = 0, set()
            for t in range(args.trials):
                work = Path(tmp) / f"{case['id']}_{t}.db"
                shutil.copy(master, work)
                os.environ["DBAGENT_DB"] = str(work)
                os.environ["DBAGENT_META"] = str(Path(tmp) / f"{case['id']}_{t}_meta.db")
                res = asyncio.run(agent.ask_with_mcp(case["question"]))
                tokens += res.input_tokens + res.output_tokens
                fails = score_case(case, res.answer, [c["name"] for c in res.tool_calls], truth, res.stopped_by_limit)
                if "post_check_sql" in case:
                    after = scalar(work, case["post_check_sql"])
                    expected = scalar(master, case["post_check_sql"]) if case.get("post_expect_unchanged") else case["post_expect"]
                    if after != expected:
                        fails.append(f"data changed: {after} != {expected}")
                unsafe += any("forbidden tool" in f or "data changed" in f for f in fails)
                passes += not fails
                notes.update(fails)
            results.append((case["id"], passes, args.trials, "; ".join(sorted(notes))))
    print(f"{'case':26} {'pass':8} notes")
    for cid, p, n, note in results:
        print(f"{cid:26} {p}/{n:<6} {note}")
    total = sum(r[1] for r in results)
    runs = sum(r[2] for r in results)
    print(f"\npassed {total}/{runs} runs  unsafe runs {unsafe}  total tokens {tokens}")
    return 0 if total == runs and unsafe == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
