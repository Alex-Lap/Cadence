"""Score a syllabus extraction against a hand-checked answer file.

Pure functions, no LLM: tests/test_eval_score.py covers them directly.

What is measured, per syllabus:
  items     -- graded items found (recall) and invented (extras)
  kind      -- deliverable vs grading category vs participation, on matched items
  weight    -- share of the grade, within half a percentage point
  due       -- the right due date (or due week), on items that have one
  invented  -- items that have NO date in the syllabus but came back with one.
               The worst error: a made-up deadline silently drives the schedule.
  handout   -- the week work can start, where the syllabus says
  meetings  -- class meeting (weekday, start, end) slots, precision and recall
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from app.agent.tools.meetings import DAYS, meeting_rows

MATCH_THRESHOLD = 0.6
WEIGHT_TOLERANCE = 0.005


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def similarity(gold_names: list[str], predicted: str) -> float:
    """Best title similarity. Numbers must agree exactly: "Project 1" and
    "Project 2" are 90% similar as strings and 0% the same assignment."""
    p = _norm(predicted)
    best = 0.0
    for name in gold_names:
        g = _norm(name)
        if not _numbers(g) <= _numbers(p):
            continue
        if g == p or (g and (f" {g} " in f" {p} " or f" {p} " in f" {g} ")):
            return 1.0
        best = max(best, SequenceMatcher(None, g, p).ratio())
    return best


def match(gold_items: list[dict], predicted: list) -> list[tuple[int, int]]:
    """Greedy one-to-one pairing of gold and predicted items, best first."""
    pairs = []
    for gi, g in enumerate(gold_items):
        names = [g["title"], *g.get("aliases", [])]
        for pi, p in enumerate(predicted):
            s = similarity(names, p.title)
            if s >= MATCH_THRESHOLD:
                same_kind = "kind" in g and kind_of(p) == g["kind"]
                pairs.append((s, same_kind, gi, pi))
    used_g, used_p, out = set(), set(), []
    for _, _, gi, pi in sorted(pairs, key=lambda t: (t[0], t[1], -t[2], -t[3]), reverse=True):
        if gi not in used_g and pi not in used_p:
            used_g.add(gi)
            used_p.add(pi)
            out.append((gi, pi))
    return out


def kind_of(item) -> str:
    if getattr(item, "is_participation", False):
        return "participation"
    if item.is_category:
        return "category"
    return "deliverable"


def week_friday(term_start: date, week: int) -> date:
    return term_start + timedelta(weeks=week - 1, days=4)


def due_correct(gold_due: dict, item, term_start: date) -> bool:
    if "date" in gold_due:
        return item.due_at is not None and item.due_at.date() == date.fromisoformat(gold_due["date"])
    week = gold_due["week"]
    if item.due_week == week:
        return True
    # A week-based deadline is right if the date lands anywhere in that week
    # ("start of class in Week 5" may come back as the Monday or the Friday).
    if item.due_at is None:
        return False
    monday = term_start + timedelta(weeks=week - 1)
    return monday <= item.due_at.date() <= monday + timedelta(days=6)


@dataclass
class Tally:
    right: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.total += 1
        self.right += int(ok)

    @property
    def rate(self) -> float | None:
        return self.right / self.total if self.total else None


@dataclass
class Score:
    name: str
    items_found: Tally = field(default_factory=Tally)
    extras: list[str] = field(default_factory=list)
    kind: Tally = field(default_factory=Tally)
    weight: Tally = field(default_factory=Tally)
    due: Tally = field(default_factory=Tally)
    invented_dates: list[str] = field(default_factory=list)
    undated_kept: Tally = field(default_factory=Tally)
    handout: Tally = field(default_factory=Tally)
    meetings_found: Tally = field(default_factory=Tally)
    meetings_extra: int = 0
    problems: list[str] = field(default_factory=list)


def _slots(gold_meetings: list[dict]) -> list[tuple[int, set[str], set[str]]]:
    out = []
    for m in gold_meetings:
        starts = set(m["start"] if isinstance(m["start"], list) else [m["start"]])
        ends = set(m["end"] if isinstance(m["end"], list) else [m["end"]])
        for d in m["days"]:
            out.append((DAYS.index(d), starts, ends))
    return out


def score(gold: dict, extraction) -> Score:
    s = Score(gold["name"])
    term_start = date.fromisoformat(gold["term_start"])
    predicted = [a for c in extraction.courses for a in c.assignments]
    gold_items = gold["items"]
    pairs = dict(match(gold_items, predicted))

    for gi, g in enumerate(gold_items):
        found = gi in pairs
        s.items_found.add(found)
        if not found:
            s.problems.append(f"missing: {g['title']}")
            continue
        p = predicted[pairs[gi]]

        ok = kind_of(p) == g["kind"]
        s.kind.add(ok)
        if not ok:
            s.problems.append(f"kind: {g['title']} is {g['kind']}, got {kind_of(p)}")

        if g.get("weight") is not None:
            ok = p.weight is not None and abs(p.weight - g["weight"]) <= WEIGHT_TOLERANCE
            s.weight.add(ok)
            if not ok:
                s.problems.append(f"weight: {g['title']} is {g['weight']}, got {p.weight}")

        if g["due"] is None:
            kept = p.due_at is None and p.due_week is None
            s.undated_kept.add(kept)
            if not kept:
                got = p.due_at.date().isoformat() if p.due_at else f"week {p.due_week}"
                s.invented_dates.append(f"{g['title']} -> {got}")
        else:
            ok = due_correct(g["due"], p, term_start)
            s.due.add(ok)
            if not ok:
                got = p.due_at.date().isoformat() if p.due_at else f"week {p.due_week}"
                s.problems.append(f"due: {g['title']} expected {g['due']}, got {got}")

        if g.get("available_week") is not None:
            want = term_start + timedelta(weeks=g["available_week"] - 1)
            ok = p.available_week == g["available_week"] or (
                p.available_at is not None and p.available_at.date() == want
            )
            s.handout.add(ok)
            if not ok:
                s.problems.append(
                    f"handout: {g['title']} expected week {g['available_week']}, got {p.available_week}"
                )

    optional = [_norm(o) for o in gold.get("optional_items", [])]
    matched_p = set(pairs.values())
    for pi, p in enumerate(predicted):
        if pi in matched_p:
            continue
        if any(similarity([o], p.title) >= MATCH_THRESHOLD for o in optional):
            continue
        s.extras.append(p.title)

    # Meetings: compare as (weekday, start, end) slots.
    rows = []
    for c in extraction.courses:
        r, _ = meeting_rows(c.code, c.meetings)
        rows += r
    got = [(r.weekday, r.start.strftime("%H:%M"), r.end.strftime("%H:%M")) for r in rows]
    unclaimed = list(got)
    for day, starts, ends in _slots(gold.get("meetings", [])):
        hit = next((g for g in unclaimed if g[0] == day and g[1] in starts and g[2] in ends), None)
        s.meetings_found.add(hit is not None)
        if hit:
            unclaimed.remove(hit)
        else:
            s.problems.append(f"meeting missing: {DAYS[day]} {sorted(starts)[0]}-{sorted(ends)[0]}")
    s.meetings_extra = len(unclaimed)
    for g in unclaimed:
        s.problems.append(f"meeting extra: {DAYS[g[0]]} {g[1]}-{g[2]}")
    return s
