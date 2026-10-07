"""Run the syllabus reader on every answer file in evals/gold and score it.

    docker compose exec api python -m evals.run                 # default model
    docker compose exec api python -m evals.run --model claude-sonnet-4-5
    docker compose exec api python -m evals.run --only cis6307

Calls the real LLM (one extraction per syllabus). Syllabi whose source file is
missing -- the private ones under samples/ on someone else's machine -- are
skipped, not failed. Results are printed and saved to evals/results/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pct(t) -> str:
    return "  -  " if t.rate is None else f"{t.rate * 100:4.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", help="override LLM_MODEL for this run")
    ap.add_argument("--only", help="run one answer file, by name (e.g. cis6307)")
    args = ap.parse_args()
    if args.model:
        os.environ["LLM_MODEL"] = args.model  # before settings are first read

    sys.path.insert(0, str(ROOT))
    from app.agent.graph import node_parse
    from app.agent.tools.parse_syllabus import extract_text
    from app.config import get_settings
    from evals.score import Tally, score

    model = get_settings().llm_model
    golds = sorted((ROOT / "evals" / "gold").glob("*.json"))
    if args.only:
        golds = [g for g in golds if g.stem == args.only]

    results, totals = [], {k: Tally() for k in
                          ["items_found", "kind", "weight", "due", "undated_kept", "handout", "meetings_found"]}
    extras = invented = 0
    print(f"model: {model}\n")
    for path in golds:
        gold = json.loads(path.read_text())
        src = ROOT / gold["source"]
        if not src.exists():
            print(f"skip  {path.stem}: {gold['source']} not found")
            continue
        text = extract_text(src.read_bytes())
        t0 = time.time()
        out = node_parse({"syllabus_text": text, "term_start": date.fromisoformat(gold["term_start"])})
        s = score(gold, out["extraction"])
        secs = time.time() - t0

        for k, tally in totals.items():
            part = getattr(s, k)
            tally.right += part.right
            tally.total += part.total
        extras += len(s.extras)
        invented += len(s.invented_dates)

        print(f"{path.stem}  ({secs:.1f}s)  {gold['name']}")
        print(f"  items {s.items_found.right}/{s.items_found.total}  kind {pct(s.kind)}  "
              f"weight {pct(s.weight)}  due {pct(s.due)}  handout {pct(s.handout)}  "
              f"meetings {s.meetings_found.right}/{s.meetings_found.total}")
        for msg in s.invented_dates:
            print(f"  ! invented date: {msg}")
        for msg in s.problems:
            print(f"  - {msg}")
        for e in s.extras:
            print(f"  + extra item: {e}")
        print()
        results.append({
            "gold": path.stem, "seconds": round(secs, 1),
            "items": [s.items_found.right, s.items_found.total],
            "kind": [s.kind.right, s.kind.total], "weight": [s.weight.right, s.weight.total],
            "due": [s.due.right, s.due.total], "handout": [s.handout.right, s.handout.total],
            "undated_kept": [s.undated_kept.right, s.undated_kept.total],
            "meetings": [s.meetings_found.right, s.meetings_found.total],
            "meetings_extra": s.meetings_extra,
            "invented_dates": s.invented_dates, "extras": s.extras, "problems": s.problems,
        })

    if not results:
        print("nothing ran")
        return 1

    print("=" * 60)
    print(f"overall ({len(results)} syllabi, {model})")
    for k, label in [("items_found", "items found"), ("kind", "kind right"),
                     ("weight", "weight right"), ("due", "due date right"),
                     ("handout", "handout week right"), ("undated_kept", "undated kept undated"),
                     ("meetings_found", "meetings found")]:
        t = totals[k]
        print(f"  {label:<22} {pct(t)}  ({t.right}/{t.total})")
    print(f"  {'invented dates':<22} {invented}")
    print(f"  {'extra items':<22} {extras}")

    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"{stamp}-{model.replace('/', '_')}.json"
    out.write_text(json.dumps({
        "model": model, "ran_at": stamp,
        "totals": {k: [t.right, t.total] for k, t in totals.items()},
        "invented_dates": invented, "extras": extras, "syllabi": results,
    }, indent=2))
    print(f"\nsaved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
