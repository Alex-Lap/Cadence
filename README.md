# Cadence

An AI agent that turns syllabi and assignments into a personalized study
schedule. The scheduler is deterministic code the agent *calls as a tool* —
not "ask the LLM to make a schedule."

## Architecture

```
POST /api/syllabus  ──►  LangGraph agent
                          ├─ parse_syllabus   (LLM, structured output)
                          ├─ estimate_effort  (LLM, per-assignment hours)
                          └─ build_schedule   (deterministic, app/scheduler)
                                    │
                              Postgres (ScheduleBlock)
                                    │
GET  /api/schedule  ◄─────────────┘
```

`app/llm/provider.py` is the only file that touches a vendor SDK, so the
provider is a config switch (`LLM_PROVIDER=anthropic|openai`).

## Layout

| Path | What lives there |
| --- | --- |
| `app/models.py` | User, Course, Assignment, Availability, ScheduleBlock |
| `app/schemas.py` | Pydantic contracts — also the LLM structured-output shapes |
| `app/scheduler/core.py` | EDF + effort spreading + max-hours/day. No LLM. |
| `app/agent/graph.py` | LangGraph state machine wiring the three tools |
| `app/agent/tools/` | `parse_syllabus`, `estimate_effort` |
| `app/api/routes.py` | FastAPI endpoints |
| `tests/test_scheduler.py` | Acceptance tests for the scheduler (written first) |

## Local dev

```bash
cp .env.example .env        # add your API key
docker compose up --build
docker compose exec api alembic revision --autogenerate -m "initial"
docker compose exec api alembic upgrade head
```

API at http://localhost:8000/docs

Tests:

```bash
pytest
```

## Week 1 checklist

- [ ] `alembic revision --autogenerate` produces a clean initial migration
- [ ] `app/scheduler/core.py::build_schedule` — the four tests in
      `tests/test_scheduler.py` pass (drop the `xfail` marks as you go)
- [ ] `parse_syllabus` returns a valid `SyllabusExtraction` from a real PDF
- [ ] `estimate_effort` returns hours per assignment
- [ ] `node_*` functions in `app/agent/graph.py` wire the three together
- [ ] `POST /api/syllabus` → `GET /api/schedule` round-trips
- [ ] Tested against 3–5 real syllabi

Start with the scheduler. It has no dependencies, the tests are already
written, and it is the part interviewers will ask about.
