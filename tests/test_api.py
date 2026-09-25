"""End-to-end tests for the HTTP surface.

The LLM is stubbed: `build_graph` is replaced with a fake whose invoke() returns
a canned extraction. Everything else is real -- real Postgres, real scheduler,
real persistence. Each test below corresponds to a bug that reached production
during week 2 and was found by hand.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import app.api.routes as routes
from app.schemas import ParsedAssignment, ParsedCourse, SyllabusExtraction

TODAY = date.today()


def dt(days: int) -> datetime:
    """A timezone-aware datetime `days` from today, as the extractor produces."""
    return datetime.combine(TODAY + timedelta(days=days), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )


def _extraction() -> SyllabusExtraction:
    """One course shaped like CIS 6307: dated work, an undated deliverable, and
    a bucket the model mislabelled."""
    return SyllabusExtraction(
        courses=[
            ParsedCourse(
                code="CIS 6307",
                title="Internet Data Streaming",
                term="Fall 2026",
                assignments=[
                    ParsedAssignment(
                        title="Project 1",
                        due_at=dt(20),
                        available_at=dt(-5),
                        weight=0.1,
                    ),
                    ParsedAssignment(
                        title="Project 2",
                        due_at=dt(40),
                        available_at=dt(15),
                        weight=0.1,
                    ),
                    ParsedAssignment(title="Final Exam", weight=0.3, is_category=True),
                    ParsedAssignment(title="Paper Presentation", weight=0.1),
                    ParsedAssignment(title="Attendance", weight=0.1, is_category=True),
                ],
            )
        ]
    )


class _FakeGraph:
    def invoke(self, state):
        return {
            "extraction": _extraction(),
            "hours": {
                "CIS 6307::Project 1": 8.0,
                "CIS 6307::Project 2": 8.0,
                "CIS 6307::Paper Presentation": 6.0,
                "CIS 6307::Final Exam": 20.0,
            },
            "trace": ["parsed 1 course(s)", "estimated CIS 6307"],
        }

    def stream(self, state, stream_mode="updates"):
        """Mimic LangGraph's updates mode: one dict per completed node, carrying
        only that node's delta."""
        yield {
            "parse": {
                "extraction": _extraction(),
                "trace": ["parsed 1 course(s), 5 item(s) - 3 without a date"],
            }
        }
        yield {
            "estimate": {
                "hours": {
                    "CIS 6307::Project 1": 8.0,
                    "CIS 6307::Project 2": 8.0,
                    "CIS 6307::Paper Presentation": 6.0,
                    "CIS 6307::Final Exam": 20.0,
                },
                "trace": ["estimated CIS 6307: 42.0h across 4 item(s)"],
            }
        }


@pytest.fixture
def stub_agent(monkeypatch):
    monkeypatch.setattr(routes, "build_graph", lambda: _FakeGraph())
    monkeypatch.setattr(routes, "extract_text", lambda raw: "syllabus text")


@pytest.fixture
def uploaded(client, stub_agent):
    resp = client.post(
        "/api/syllabus",
        files={"file": ("syllabus.docx", b"PK\x03\x04fake", "application/octet-stream")},
        data={"term_start": str(TODAY - timedelta(days=30))},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- upload


def test_upload_persists_everything_including_categories(uploaded):
    """Nothing is dropped. Categories and undated work are stored, not skipped --
    a Final Exam worth 30% silently vanishing was the original bug."""
    assert uploaded["courses"] == ["CIS 6307"]
    assert uploaded["scheduled"] == 2          # only the two dated projects
    assert uploaded["blocks"] > 0
    assert uploaded["needs_date"] == ["Paper Presentation"]
    assert sorted(uploaded["categories"]) == ["Attendance", "Final Exam"]


def test_upload_stores_all_five_assignments(client, uploaded):
    rows = client.get("/api/assignments").json()
    assert len(rows) == 5


def test_upload_rejects_unknown_file_type(client, monkeypatch):
    resp = client.post(
        "/api/syllabus", files={"file": ("notes.txt", b"just some text", "text/plain")}
    )
    assert resp.status_code == 415


def test_upload_rejects_empty_file(client):
    resp = client.post("/api/syllabus", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert resp.status_code == 400


# ---------------------------------------------------------------- listing


def test_needs_date_filter_excludes_categories(client, uploaded):
    """The filter must agree with the field it is named after. It used to test
    `due_at is None`, which matched undated categories too."""
    rows = client.get("/api/assignments?needs_date=true").json()
    assert [r["title"] for r in rows] == ["Paper Presentation"]
    assert all(r["needs_date"] and not r["is_category"] for r in rows)


def test_listing_sorts_mixed_dated_and_undated(client, uploaded):
    """Sorting once compared `datetime` against `date.max` and raised
    TypeError as soon as any row had a date."""
    rows = client.get("/api/assignments").json()
    dated = [r for r in rows if r["due_at"]]
    assert [r["title"] for r in dated] == ["Project 1", "Project 2"]


def test_courses_endpoint(client, uploaded):
    courses = client.get("/api/courses").json()
    assert len(courses) == 1
    assert courses[0]["code"] == "CIS 6307"
    assert courses[0]["assignments"] == 5


def test_unknown_user_is_404(client):
    assert client.get("/api/assignments?external_id=nobody").status_code == 404


# ---------------------------------------------------------------- patch


def _find(client, title):
    return next(r for r in client.get("/api/assignments").json() if r["title"] == title)


def test_patch_naive_datetime_against_aware_column(client, uploaded):
    """Paper Presentation has no available_at, Project 1 does. Patching Project 1
    with a naive datetime used to raise TypeError comparing aware to naive."""
    row = _find(client, "Project 1")
    assert row["available_at"] is not None
    resp = client.patch(
        f"/api/assignments/{row['id']}",
        json={"due_at": (TODAY + timedelta(days=25)).isoformat() + "T00:00:00"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["due_at"].startswith(str(TODAY + timedelta(days=25)))


def test_patch_rejects_available_after_due(client, uploaded):
    row = _find(client, "Project 1")
    resp = client.patch(
        f"/api/assignments/{row['id']}",
        json={"due_at": (TODAY - timedelta(days=10)).isoformat() + "T00:00:00"},
    )
    assert resp.status_code == 422


def test_patch_rejects_nonpositive_hours(client, uploaded):
    row = _find(client, "Project 1")
    resp = client.patch(f"/api/assignments/{row['id']}", json={"estimated_hours": 0})
    assert resp.status_code == 422


def test_patch_does_not_reschedule(client, uploaded):
    """A form with five corrections should cost one rebuild, not five."""
    before = len(client.get("/api/schedule").json()["blocks"])
    row = _find(client, "Paper Presentation")
    client.patch(
        f"/api/assignments/{row['id']}",
        json={"due_at": (TODAY + timedelta(days=30)).isoformat() + "T00:00:00"},
    )
    assert len(client.get("/api/schedule").json()["blocks"]) == before


def test_patch_on_unknown_id_is_404(client, uploaded):
    resp = client.patch(
        "/api/assignments/00000000-0000-0000-0000-000000000000", json={"estimated_hours": 3}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------- reschedule


def test_supplying_a_date_then_rescheduling_adds_work(client, uploaded):
    row = _find(client, "Paper Presentation")
    client.patch(
        f"/api/assignments/{row['id']}",
        json={"due_at": (TODAY + timedelta(days=30)).isoformat() + "T00:00:00"},
    )
    summary = client.post("/api/reschedule").json()
    assert summary["scheduled"] == 3
    assert summary["needs_date"] == []


def test_promoting_a_category_schedules_it(client, uploaded):
    """The model mislabels undated exams as categories. The user must be able to
    say otherwise and have the schedule rebuild around the correction."""
    row = _find(client, "Final Exam")
    assert row["is_category"] is True
    resp = client.patch(
        f"/api/assignments/{row['id']}",
        json={
            "is_category": False,
            "due_at": (TODAY + timedelta(days=60)).isoformat() + "T00:00:00",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_category"] is False

    summary = client.post("/api/reschedule").json()
    assert summary["scheduled"] == 3
    assert summary["categories"] == ["Attendance"]


def test_reschedule_is_idempotent(client, uploaded):
    first = client.post("/api/reschedule").json()
    second = client.post("/api/reschedule").json()
    assert first["blocks"] == second["blocks"]
    assert first["scheduled"] == second["scheduled"]


def test_pinned_blocks_survive_and_reduce_remaining_hours(client, uploaded, db):
    """Dragging a block is a commitment: it stays put, and its hours are not
    planned a second time."""
    from sqlalchemy import select

    from app.models import ScheduleBlock

    block = db.scalars(select(ScheduleBlock).limit(1)).first()
    assert block is not None
    block.pinned = True
    pinned_day, pinned_hours = block.day, block.hours
    db.commit()

    summary = client.post("/api/reschedule").json()
    assert summary["pinned_kept"] == 1

    blocks = client.get("/api/schedule").json()["blocks"]
    kept = [b for b in blocks if b["pinned"]]
    assert len(kept) == 1
    assert kept[0]["day"] == str(pinned_day)
    assert kept[0]["hours"] == pinned_hours

    total = sum(b["hours"] for b in blocks)
    assert total == pytest.approx(16.0, abs=0.5)  # 8 + 8, pinned hours not doubled


# ---------------------------------------------------------------- schedule


def test_schedule_is_ordered_and_within_windows(client, uploaded):
    blocks = client.get("/api/schedule").json()["blocks"]
    assert blocks
    keys = [(b["day"], b["start_time"]) for b in blocks]
    assert keys == sorted(keys)
    for b in blocks:
        assert b["hours"] * 4 % 1 == 0          # quarter hours only
        assert b["start_time"].endswith(":00")  # no microsecond drift


def test_project_2_is_not_scheduled_before_its_handout(client, uploaded):
    """earliest_start must hold end to end, not just in the scheduler unit test."""
    blocks = client.get("/api/schedule").json()["blocks"]
    p2 = [b for b in blocks if b["assignment_title"] == "Project 2"]
    assert p2, "Project 2 should be scheduled"
    assert min(b["day"] for b in p2) >= str(TODAY + timedelta(days=15))


# ---------------------------------------------------------------- streaming


def _events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    out = []
    for frame in body.strip().split("\n\n"):
        name, payload = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if name:
            out.append((name, payload))
    return out


def test_stream_emits_a_node_event_per_graph_step(client, stub_agent):
    resp = client.post(
        "/api/syllabus/stream",
        files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
        data={"term_start": str(TODAY - timedelta(days=30))},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _events(resp.text)
    names = [name for name, _ in events]
    assert names == ["start", "node", "node", "persisted", "scheduled", "done"]

    nodes = [d["node"] for name, d in events if name == "node"]
    assert nodes == ["parse", "estimate"]
    assert all(d["trace"] for name, d in events if name == "node")


def test_stream_persists_and_schedules_like_the_plain_endpoint(client, stub_agent):
    resp = client.post(
        "/api/syllabus/stream",
        files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
        data={"term_start": str(TODAY - timedelta(days=30))},
    )
    scheduled = next(d for name, d in _events(resp.text) if name == "scheduled")
    assert scheduled["scheduled"] == 2
    assert scheduled["needs_date"] == ["Paper Presentation"]
    assert sorted(scheduled["categories"]) == ["Attendance", "Final Exam"]

    assert len(client.get("/api/assignments").json()) == 5
    assert client.get("/api/schedule").json()["blocks"]


def test_stream_validates_before_opening_the_stream(client):
    """A bad upload must be a real 4xx, not a 200 whose body says it failed."""
    resp = client.post(
        "/api/syllabus/stream", files={"file": ("notes.txt", b"plain text", "text/plain")}
    )
    assert resp.status_code == 415
    assert not resp.headers["content-type"].startswith("text/event-stream")


def test_stream_reports_a_mid_stream_failure_as_an_event(client, monkeypatch):
    """Once the 200 is sent, failure can only travel as an event."""

    class _Boom:
        def stream(self, state, stream_mode="updates"):
            raise RuntimeError("model unavailable")
            yield  # pragma: no cover

    monkeypatch.setattr(routes, "extract_text", lambda raw: "syllabus text")
    monkeypatch.setattr(routes, "build_graph", lambda: _Boom())

    resp = client.post(
        "/api/syllabus/stream",
        files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
    )
    assert resp.status_code == 200
    events = _events(resp.text)
    assert events[-1][0] == "error"
    assert "model unavailable" in events[-1][1]["detail"]


# ---------------------------------------------------------------- blocks


def test_dragging_a_block_pins_it(client, uploaded):
    blocks = client.get("/api/schedule").json()["blocks"]
    first = blocks[0]
    assert first["pinned"] is False

    new_day = str(TODAY + timedelta(days=3))
    resp = client.patch(
        f"/api/blocks/{first['id']}",
        json={"day": new_day, "start_time": "09:00:00"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["day"] == new_day
    assert body["start_time"] == "09:00:00"
    assert body["pinned"] is True


def test_a_dragged_block_survives_rescheduling(client, uploaded):
    blocks = client.get("/api/schedule").json()["blocks"]
    first = blocks[0]
    moved_day = str(TODAY + timedelta(days=4))
    client.patch(f"/api/blocks/{first['id']}", json={"day": moved_day})

    summary = client.post("/api/reschedule").json()
    assert summary["pinned_kept"] == 1

    after = client.get("/api/schedule").json()["blocks"]
    kept = [b for b in after if b["pinned"]]
    assert len(kept) == 1
    assert kept[0]["day"] == moved_day


def test_empty_block_patch_is_422(client, uploaded):
    first = client.get("/api/schedule").json()["blocks"][0]
    assert client.patch(f"/api/blocks/{first['id']}", json={}).status_code == 422


def test_patching_an_unknown_block_is_404(client, uploaded):
    resp = client.patch(
        "/api/blocks/00000000-0000-0000-0000-000000000000", json={"hours": 2}
    )
    assert resp.status_code == 404


def test_schedule_blocks_carry_ids(client, uploaded):
    blocks = client.get("/api/schedule").json()["blocks"]
    assert all(b["id"] for b in blocks)
    assert len({b["id"] for b in blocks}) == len(blocks)


# ---------------------------------------------------------------- data hygiene


def test_reuploading_a_course_replaces_it(client, stub_agent):
    """Uploading the same syllabus twice used to stack a second copy of the
    course, doubling every hour on the calendar."""
    for _ in range(2):
        client.post(
            "/api/syllabus",
            files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
            data={"term_start": str(TODAY - timedelta(days=30))},
        )
    assert len(client.get("/api/courses").json()) == 1
    assert len(client.get("/api/assignments").json()) == 5


def test_deleting_a_course_removes_its_work(client, uploaded):
    course = client.get("/api/courses").json()[0]
    resp = client.delete(f"/api/courses/{course['id']}")
    assert resp.status_code == 200
    assert client.get("/api/courses").json() == []
    assert client.get("/api/assignments").json() == []
    assert client.get("/api/schedule").json()["blocks"] == []


def test_dropping_a_block_onto_another_pinned_block_is_refused(client, uploaded):
    """Pinned blocks are never moved by the scheduler, so an overlap between two
    of them would be permanent -- and the calendar would squash both."""
    a, b = client.get("/api/schedule").json()["blocks"][:2]
    day = str(TODAY + timedelta(days=5))
    assert client.patch(f"/api/blocks/{a['id']}", json={"day": day, "start_time": "18:00:00", "hours": 2}).status_code == 200
    resp = client.patch(f"/api/blocks/{b['id']}", json={"day": day, "start_time": "19:00:00"})
    assert resp.status_code == 409
    assert "overlaps" in resp.json()["detail"]


def test_adjacent_pinned_blocks_are_fine(client, uploaded):
    a, b = client.get("/api/schedule").json()["blocks"][:2]
    day = str(TODAY + timedelta(days=5))
    client.patch(f"/api/blocks/{a['id']}", json={"day": day, "start_time": "18:00:00", "hours": 2})
    resp = client.patch(f"/api/blocks/{b['id']}", json={"day": day, "start_time": "20:00:00"})
    assert resp.status_code == 200


def test_blocks_can_be_resized_down_to_fifteen_minutes(client, uploaded):
    first = client.get("/api/schedule").json()["blocks"][0]
    resp = client.patch(f"/api/blocks/{first['id']}", json={"hours": 0.25})
    assert resp.status_code == 200, resp.text
    assert resp.json()["hours"] == 0.25


def test_blocks_cannot_be_shorter_than_fifteen_minutes(client, uploaded):
    first = client.get("/api/schedule").json()["blocks"][0]
    resp = client.patch(f"/api/blocks/{first['id']}", json={"hours": 0.1})
    assert resp.status_code == 422
    assert "15 minutes" in resp.json()["detail"]


# ---------------------------------------------------------------- colours


def test_assignments_start_with_no_colour(client, uploaded):
    assert all(a["color"] is None for a in client.get("/api/assignments").json())


def test_setting_a_task_colour(client, uploaded):
    row = _find(client, "Project 1")
    resp = client.patch(f"/api/assignments/{row['id']}", json={"color": "#e9a25b"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["color"] == "#e9a25b"
    assert _find(client, "Project 1")["color"] == "#e9a25b"


def test_clearing_a_task_colour_returns_to_automatic(client, uploaded):
    row = _find(client, "Project 1")
    client.patch(f"/api/assignments/{row['id']}", json={"color": "#e9a25b"})
    resp = client.patch(f"/api/assignments/{row['id']}", json={"color": None})
    assert resp.json()["color"] is None


def test_rejects_a_malformed_colour(client, uploaded):
    row = _find(client, "Project 1")
    for bad in ["red", "#fff", "e9a25b", "#gggggg"]:
        resp = client.patch(f"/api/assignments/{row['id']}", json={"color": bad})
        assert resp.status_code == 422, bad
