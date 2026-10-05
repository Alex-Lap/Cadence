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
from app.schemas import ParsedAssignment, ParsedCourse, ParsedMeeting, SyllabusExtraction

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
                # Lecture Tue/Thu, plus a lab whose end time has the kind of typo
                # real syllabi have (a 4h40m lab).
                meetings=[
                    ParsedMeeting(
                        days=["Tue", "Thu"],
                        start_time="18:00",
                        end_time="20:40",
                        source_text="Lecture: TR 6:00-8:40 PM",
                    ),
                    ParsedMeeting(
                        days=["Wed"],
                        start_time="18:00",
                        end_time="22:40",
                        kind="lab",
                        source_text="Lab: W 6:00-10:40 PM",
                    ),
                ],
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
    # Attendance came back as a category, but it's credit for showing up:
    # filed as participation, so it is neither a category nor waiting on a date.
    assert uploaded["categories"] == ["Final Exam"]


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
    assert summary["categories"] == []


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
    assert scheduled["categories"] == ["Final Exam"]

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


# ---------------------------------------------------------------- commitments


def _blocks_on(client, day):
    return [b for b in client.get("/api/schedule").json()["blocks"] if b["day"] == str(day)]


def _minutes(t: str) -> int:
    h, m, *_ = map(int, t.split(":"))
    return h * 60 + m


def test_no_settings_and_no_commitments_keeps_the_old_defaults(client, uploaded):
    s = client.get("/api/settings").json()
    assert s["study_start"] is None and s["study_end"] is None
    assert s["effective"]["study_start"] == "18:00:00"
    # Only the syllabus's unconfirmed meetings exist; nothing the scheduler uses.
    assert all(not c["confirmed"] for c in client.get("/api/commitments").json())


def test_study_never_lands_on_a_weekly_commitment(client, uploaded):
    client.put("/api/settings", json={"study_start": "18:00", "study_end": "23:00"})
    for wd in range(7):
        resp = client.post(
            "/api/commitments",
            json={"title": "Lecture", "kind": "class", "weekday": wd,
                  "start_time": "18:00", "end_time": "20:40"},
        )
        assert resp.status_code == 201, resp.text
    blocks = client.get("/api/schedule").json()["blocks"]
    assert blocks
    for b in blocks:
        start = _minutes(b["start_time"])
        assert start >= 20 * 60 + 45 or start + b["hours"] * 60 <= 18 * 60, b


def test_study_window_is_respected(client, uploaded):
    client.put("/api/settings", json={"study_start": "09:00", "study_end": "12:00",
                                      "max_hours_per_day": 3})
    for b in client.get("/api/schedule").json()["blocks"]:
        start = _minutes(b["start_time"])
        assert 9 * 60 <= start and start + b["hours"] * 60 <= 12 * 60, b


def test_one_off_commitment_clears_its_day(client, uploaded):
    busy_day = TODAY + timedelta(days=2)
    client.put("/api/settings", json={"study_start": "18:00", "study_end": "22:00"})
    client.post("/api/commitments", json={"title": "Dentist", "on_date": str(busy_day),
                                          "start_time": "18:00", "end_time": "22:00"})
    assert _blocks_on(client, busy_day) == []


def test_deleting_a_commitment_frees_the_time(client, uploaded):
    busy_day = TODAY + timedelta(days=2)
    client.put("/api/settings", json={"study_start": "18:00", "study_end": "22:00"})
    before = _blocks_on(client, busy_day)
    c = client.post("/api/commitments", json={"title": "Shift", "on_date": str(busy_day),
                                              "start_time": "18:00", "end_time": "22:00"}).json()
    assert client.delete(f"/api/commitments/{c['id']}").status_code == 200
    assert c["id"] not in {x["id"] for x in client.get("/api/commitments").json()}
    assert len(_blocks_on(client, busy_day)) == len(before)


def test_commitment_needs_exactly_one_of_weekday_or_date(client, uploaded):
    base = {"title": "X", "start_time": "18:00", "end_time": "19:00"}
    assert client.post("/api/commitments", json=base).status_code == 422
    both = {**base, "weekday": 0, "on_date": str(TODAY)}
    assert client.post("/api/commitments", json=both).status_code == 422


def test_commitment_must_end_after_it_starts(client, uploaded):
    resp = client.post("/api/commitments", json={"title": "X", "weekday": 0,
                                                  "start_time": "20:00", "end_time": "19:00"})
    assert resp.status_code == 422


def test_study_window_must_end_after_it_starts(client, uploaded):
    resp = client.put("/api/settings", json={"study_start": "22:00", "study_end": "18:00"})
    assert resp.status_code == 422


def test_dropping_a_block_onto_a_commitment_is_refused(client, uploaded):
    day = TODAY + timedelta(days=5)
    client.post("/api/commitments", json={"title": "Lecture", "on_date": str(day),
                                          "start_time": "18:00", "end_time": "20:40"})
    first = client.get("/api/schedule").json()["blocks"][0]
    resp = client.patch(f"/api/blocks/{first['id']}",
                        json={"day": str(day), "start_time": "19:00:00"})
    assert resp.status_code == 409
    assert "Lecture" in resp.json()["detail"]


def test_course_commitments_go_with_the_course(client, uploaded):
    course = client.get("/api/courses").json()[0]
    client.post("/api/commitments", json={"title": "CIS 6307 lecture", "kind": "class",
                                          "weekday": 1, "start_time": "18:00",
                                          "end_time": "20:40", "course_id": course["id"]})
    listed = client.get("/api/commitments").json()
    assert listed[0]["course_code"] == "CIS 6307"
    client.delete(f"/api/courses/{course['id']}")
    assert client.get("/api/commitments").json() == []


def test_commitment_for_someone_elses_course_is_404(client, uploaded):
    resp = client.post("/api/commitments", json={
        "title": "X", "weekday": 0, "start_time": "18:00", "end_time": "19:00",
        "course_id": "00000000-0000-0000-0000-000000000000"})
    assert resp.status_code == 404


# ---------------------------------------------------------- syllabus meetings


def _pending(client):
    return [c for c in client.get("/api/commitments").json() if not c["confirmed"]]


def test_upload_stores_meetings_unconfirmed(client, uploaded):
    rows = client.get("/api/commitments").json()
    assert sorted((c["title"], c["weekday"]) for c in rows) == [
        ("CIS 6307", 1), ("CIS 6307", 3), ("CIS 6307 lab", 2)
    ]
    assert all(not c["confirmed"] and c["source"] == "syllabus" for c in rows)
    assert all(c["course_code"] == "CIS 6307" for c in rows)
    assert rows[0]["note"]


def test_suspicious_meeting_is_flagged(client, uploaded):
    by_title = {c["title"]: c for c in _pending(client)}
    assert "4h40m" in by_title["CIS 6307 lab"]["warning"]
    assert by_title["CIS 6307"]["warning"] is None


def test_unconfirmed_meetings_do_not_block_study(client, uploaded):
    """Until confirmed, a meeting is a guess; the schedule ignores it."""
    client.put("/api/settings", json={"study_start": "18:00", "study_end": "21:00"})

    def shape():
        return [(b["day"], b["start_time"], b["hours"])
                for b in client.get("/api/schedule").json()["blocks"]]

    with_pending = shape()
    for c in _pending(client):
        client.delete(f"/api/commitments/{c['id']}")
    assert shape() == with_pending


def test_confirming_a_meeting_schedules_around_it(client, uploaded):
    client.put("/api/settings", json={"study_start": "18:00", "study_end": "23:00"})
    for c in _pending(client):
        if c["title"] == "CIS 6307":
            resp = client.patch(f"/api/commitments/{c['id']}", json={"confirmed": True})
            assert resp.status_code == 200, resp.text
            assert resp.json()["confirmed"] is True
    for b in client.get("/api/schedule").json()["blocks"]:
        if b["pinned"]:
            continue
        weekday = date.fromisoformat(b["day"]).weekday()
        if weekday in (1, 3):
            assert _minutes(b["start_time"]) >= 20 * 60 + 45, b


def test_correcting_and_confirming_the_typo(client, uploaded):
    lab = next(c for c in _pending(client) if c["title"] == "CIS 6307 lab")
    resp = client.patch(f"/api/commitments/{lab['id']}",
                        json={"end_time": "20:40", "confirmed": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["end_time"] == "20:40:00" and body["warning"] is None


def test_patch_rejects_end_before_start(client, uploaded):
    c = _pending(client)[0]
    resp = client.patch(f"/api/commitments/{c['id']}", json={"end_time": "17:00"})
    assert resp.status_code == 422


def test_reupload_replaces_meetings(client, stub_agent):
    for _ in range(2):
        client.post(
            "/api/syllabus",
            files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
            data={"term_start": str(TODAY - timedelta(days=30))},
        )
    assert len(client.get("/api/commitments").json()) == 3


def test_meetings_start_at_term_start(client, uploaded):
    c = client.get("/api/commitments").json()[0]
    assert c["starts_on"] == str(TODAY - timedelta(days=30))


# ------------------------------------------------------- participation


def test_attendance_never_needs_input(client, monkeypatch):
    """Attendance is graded by showing up: no date to ask for, nothing to plan --
    even when the model files it as a category or an undated deliverable."""
    extraction = _extraction()
    # The stub already has "Attendance" filed as a category; add an undated one.
    extraction.courses[0].assignments.append(
        ParsedAssignment(title="Class Participation", weight=0.05)
    )

    class Graph(_FakeGraph):
        def invoke(self, state):
            return {**super().invoke(state), "extraction": extraction}

    monkeypatch.setattr(routes, "build_graph", lambda: Graph())
    monkeypatch.setattr(routes, "extract_text", lambda raw: "syllabus text")
    resp = client.post(
        "/api/syllabus",
        files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
        data={"term_start": str(TODAY - timedelta(days=30))},
    )
    assert resp.status_code == 200, resp.text
    assert "Attendance" not in resp.json()["needs_date"]
    assert "Attendance" not in resp.json()["categories"]

    rows = {a["title"]: a for a in client.get("/api/assignments").json()}
    for t in ("Attendance", "Class Participation"):
        assert rows[t]["is_participation"] and not rows[t]["needs_date"]
        assert not rows[t]["is_category"]
    waiting = {a["title"] for a in client.get("/api/assignments?needs_date=true").json()}
    assert "Attendance" not in waiting

    titles = {b["assignment_title"] for b in client.get("/api/schedule").json()["blocks"]}
    assert "Attendance" not in titles and "Class Participation" not in titles


# ---------------------------------------------------------------- replanning


def _shape(client):
    return sorted(
        (b["assignment_id"], b["day"], b["start_time"], b["hours"])
        for b in client.get("/api/schedule").json()["blocks"]
        if not b["pinned"]
    )


def test_rebuilding_an_unchanged_plan_moves_nothing(client, uploaded):
    before = _shape(client)
    summary = client.post("/api/reschedule").json()
    assert summary["churn"] == {"kept": len(before), "moved": 0, "added": 0}
    assert _shape(client) == before


def test_a_new_commitment_only_moves_what_it_hits(client, uploaded):
    blocks = [b for b in client.get("/api/schedule").json()["blocks"] if not b["pinned"]]
    target = blocks[0]
    hit = [b for b in blocks if b["day"] == target["day"]]
    resp = client.post("/api/commitments", json={
        "title": "Shift", "on_date": target["day"], "start_time": "00:00", "end_time": "23:45"})
    assert resp.status_code == 201
    after = client.get("/api/schedule").json()["blocks"]
    assert not any(b["day"] == target["day"] and not b["pinned"] for b in after)
    others = {(b["assignment_id"], b["day"], b["start_time"]) for b in blocks if b["day"] != target["day"]}
    still = {(b["assignment_id"], b["day"], b["start_time"]) for b in after}
    assert len(others - still) <= len(hit)  # at most the displaced hours ripple


def test_fresh_rebuild_reports_churn_too(client, uploaded):
    summary = client.post("/api/reschedule?fresh=true").json()
    assert set(summary["churn"]) == {"kept", "moved", "added"}


# ------------------------------------------------------------ weekly check-in


def _past_block(db, title, days_ago=2, hours=2.0, pinned=False):
    from sqlalchemy import select

    from app.models import Assignment, ScheduleBlock, User

    user = db.scalar(select(User).where(User.external_id == "demo"))
    a = db.scalar(select(Assignment).where(Assignment.title == title))
    db.add(ScheduleBlock(user_id=user.id, assignment_id=a.id,
                         day=TODAY - timedelta(days=days_ago),
                         start_time=datetime.strptime("18:00", "%H:%M").time(),
                         hours=hours, pinned=pinned))
    db.commit()
    return a


def _future_hours(client, title):
    return sum(b["hours"] for b in client.get("/api/schedule").json()["blocks"]
               if b["assignment_title"] == title and b["day"] >= str(TODAY))


def test_past_blocks_survive_rebuilds_and_count_as_done(client, uploaded, db):
    _past_block(db, "Project 1", hours=2)
    client.post("/api/reschedule")
    blocks = client.get("/api/schedule").json()["blocks"]
    assert any(b["day"] < str(TODAY) for b in blocks)  # history stays on the calendar
    assert _future_hours(client, "Project 1") == pytest.approx(6)  # 8 - 2 assumed done


def test_checkin_lists_what_was_planned(client, uploaded, db):
    _past_block(db, "Project 1", hours=2)
    _past_block(db, "Project 1", days_ago=3, hours=1.5)
    body = client.get("/api/checkin").json()
    assert body["since"] == str(TODAY - timedelta(days=3))
    assert [(t["title"], t["planned_hours"]) for t in body["tasks"]] == [("Project 1", 3.5)]


def test_doing_less_than_planned_puts_the_hours_back(client, uploaded, db):
    a = _past_block(db, "Project 1", hours=2)
    resp = client.post("/api/checkin", json={"entries": [
        {"assignment_id": str(a.id), "hours_spent": 1}]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["reviewed_blocks"] == 1
    assert _future_hours(client, "Project 1") == pytest.approx(7)  # 8 - 1 actually done
    assert client.get("/api/checkin").json()["tasks"] == []
    past = [b for b in client.get("/api/schedule").json()["blocks"] if b["day"] < str(TODAY)]
    assert past and all(b["completed"] for b in past)


def test_finishing_long_teaches_the_course(client, uploaded, db):
    a = _past_block(db, "Project 1", hours=2)
    resp = client.post("/api/checkin", json={"entries": [
        {"assignment_id": str(a.id), "hours_spent": 12, "done": True}]})
    adj = resp.json()["adjustments"]
    assert adj == [{"course_code": "CIS 6307", "before": 1.0, "after": 1.25, "rescaled": 2}]

    rows = {r["title"]: r for r in client.get("/api/assignments").json()}
    assert rows["Project 2"]["estimated_hours"] == 10       # 8 x 1.25
    assert rows["Paper Presentation"]["estimated_hours"] == 7.5  # 6 x 1.25
    assert _future_hours(client, "Project 1") == 0          # finished: never scheduled again


def test_hours_left_resets_the_estimate(client, uploaded, db):
    a = _past_block(db, "Project 1", hours=2)
    client.post("/api/checkin", json={"entries": [
        {"assignment_id": str(a.id), "hours_spent": 3, "hours_left": 2}]})
    assert _find(client, "Project 1")["estimated_hours"] == 5
    assert _future_hours(client, "Project 1") == pytest.approx(2)


def test_reupload_keeps_what_checkins_learned(client, stub_agent, uploaded, db):
    a = _past_block(db, "Project 1", hours=2)
    client.post("/api/checkin", json={"entries": [
        {"assignment_id": str(a.id), "hours_spent": 12, "done": True}]})
    client.post(
        "/api/syllabus",
        files={"file": ("s.docx", b"PK\x03\x04fake", "application/octet-stream")},
        data={"term_start": str(TODAY - timedelta(days=30))},
    )
    assert _find(client, "Project 2")["estimated_hours"] == 10


def test_checkin_rejects_unknown_assignment(client, uploaded):
    resp = client.post("/api/checkin", json={"entries": [
        {"assignment_id": "00000000-0000-0000-0000-000000000000", "hours_spent": 1}]})
    assert resp.status_code == 404


# ---------------------------------------------------------------- days off


def test_a_week_off_clears_every_day_in_it(client, uploaded):
    first, last = TODAY + timedelta(days=3), TODAY + timedelta(days=7)
    resp = client.post("/api/commitments", json={
        "title": "Fall break", "kind": "off", "on_date": str(first), "ends_on": str(last),
        "start_time": "00:00", "end_time": "23:59"})
    assert resp.status_code == 201, resp.text
    days = {b["day"] for b in client.get("/api/schedule").json()["blocks"] if not b["pinned"]}
    assert not any(str(first) <= d <= str(last) for d in days)


def test_day_off_range_must_run_forwards(client, uploaded):
    resp = client.post("/api/commitments", json={
        "title": "Break", "kind": "off", "on_date": str(TODAY + timedelta(days=5)),
        "ends_on": str(TODAY + timedelta(days=3)), "start_time": "00:00", "end_time": "23:59"})
    assert resp.status_code == 422


# ---------------------------------------------------------------- calendar export


def test_calendar_export_lists_upcoming_blocks(client, uploaded):
    resp = client.get("/api/calendar.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    upcoming = [b for b in client.get("/api/schedule").json()["blocks"] if b["day"] >= str(TODAY)]
    assert resp.text.count("BEGIN:VEVENT") == len(upcoming) > 0
    assert "SUMMARY:Work on Project" in resp.text
