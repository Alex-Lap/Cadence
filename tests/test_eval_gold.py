"""The answer files are test data too: each must be internally consistent, and a
perfect extraction built from it must score 100%."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.schemas import ParsedAssignment, ParsedCourse, ParsedMeeting, SyllabusExtraction
from evals.score import score

ROOT = Path(__file__).resolve().parent.parent
GOLDS = sorted((ROOT / "evals" / "gold").glob("*.json"))


def perfect(gold) -> SyllabusExtraction:
    items = []
    for g in gold["items"]:
        due_at = due_week = None
        if g["due"] and "date" in g["due"]:
            due_at = datetime.fromisoformat(g["due"]["date"])
        elif g["due"]:
            due_week = g["due"]["week"]
        items.append(ParsedAssignment(
            title=g["title"], weight=g["weight"], due_at=due_at, due_week=due_week,
            available_week=g.get("available_week"),
            is_category=g["kind"] == "category",
            is_participation=g["kind"] == "participation",
        ))
    meetings = []
    for m in gold.get("meetings", []):
        start = m["start"][0] if isinstance(m["start"], list) else m["start"]
        end = m["end"][0] if isinstance(m["end"], list) else m["end"]
        meetings.append(ParsedMeeting(days=m["days"], start_time=start, end_time=end, source_text="x"))
    return SyllabusExtraction(courses=[ParsedCourse(code="X", title="X", assignments=items, meetings=meetings)])


@pytest.mark.parametrize("path", GOLDS, ids=lambda p: p.stem)
def test_answer_file_is_consistent(path):
    gold = json.loads(path.read_text())
    weights = [i["weight"] for i in gold["items"] if i.get("weight") is not None]
    assert sum(weights) == pytest.approx(1.0), "weights should cover the whole grade"
    term_start = date.fromisoformat(gold["term_start"])
    for i in gold["items"]:
        assert i["kind"] in {"deliverable", "category", "participation"}
        if i["kind"] != "deliverable":
            assert i["due"] is None, f"{i['title']}: only deliverables have due dates"
        if i["due"] and "date" in i["due"]:
            d = date.fromisoformat(i["due"]["date"])
            assert term_start <= d <= term_start + timedelta(weeks=20), f"{i['title']} outside the term"


@pytest.mark.parametrize("path", GOLDS, ids=lambda p: p.stem)
def test_perfect_extraction_scores_perfectly(path):
    gold = json.loads(path.read_text())
    s = score(gold, perfect(gold))
    assert not s.problems and not s.extras and not s.invented_dates, s.problems


@pytest.mark.parametrize("path", [p for p in GOLDS if p.stem.startswith("synth")], ids=lambda p: p.stem)
def test_synthetic_syllabus_file_is_in_the_repo(path):
    gold = json.loads(path.read_text())
    assert (ROOT / gold["source"]).exists()
