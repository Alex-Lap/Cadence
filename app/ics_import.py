"""Turn someone's calendar (.ics) into commitments Cadence can plan around.

Reads the calendar with `icalendar`, expands repeats with
`recurring-ical-events` (which handles RRULE, EXDATE and time zones), then
condenses what it finds:

  * an event that repeats every week at the same time  -> one weekly commitment
    per weekday (bounded by the rule's end date, if it has one);
  * anything else with a time                           -> one-off commitments;
  * all-day events, events marked "free", cancelled ones -> skipped, counted.

Only the planning horizon (today onward) is looked at; the past doesn't matter
to a study plan. Nothing is saved here: the caller shows the result for the user
to tick, then creates the chosen ones.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

MAX_CANDIDATES = 300


@dataclass
class Candidate:
    title: str
    start_time: time
    end_time: time
    weekday: int | None = None     # weekly
    on_date: date | None = None    # one-off
    starts_on: date | None = None
    ends_on: date | None = None
    occurrences: int = 1


@dataclass
class ImportResult:
    candidates: list[Candidate] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Aware times move into the user's zone; floating times are taken as-is."""
    return dt.astimezone(tz).replace(tzinfo=None) if dt.tzinfo else dt


def _rule_end(component) -> date | None:
    rule = component.get("RRULE")
    if not rule:
        return None
    until = rule.get("UNTIL")
    if until:
        u = until[0]
        return u.date() if isinstance(u, datetime) else u
    return None


def parse_ics(
    data: bytes,
    *,
    today: date,
    horizon_days: int = 120,
    tz: str = "America/New_York",
) -> ImportResult:
    zone = ZoneInfo(tz)
    try:
        cal = icalendar.Calendar.from_ical(data)
    except Exception as exc:  # noqa: BLE001 -- any parse failure is the same to the user
        raise ValueError(f"Not a readable calendar file: {exc}") from exc

    result = ImportResult()
    window_end = today + timedelta(days=horizon_days)
    occurrences = recurring_ical_events.of(cal).between(today, window_end)

    # uid -> list of (local start, local end), plus the master component.
    by_uid: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    masters: dict[str, object] = {}
    titles: dict[str, str] = {}
    seen_skips: set[tuple[str, str]] = set()

    def skip(uid: str, reason: str) -> None:
        if (uid, reason) not in seen_skips:  # count events, not occurrences
            seen_skips.add((uid, reason))
            result.skipped[reason] += 1

    for ev in occurrences:
        uid = str(ev.get("UID") or ev.get("SUMMARY") or id(ev))
        start = ev.get("DTSTART").dt
        end_prop = ev.get("DTEND")
        if not isinstance(start, datetime):
            skip(uid, "all-day")
            continue
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            skip(uid, "cancelled")
            continue
        if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":
            skip(uid, "marked free")
            continue
        end = end_prop.dt if end_prop else start + (ev.get("DURATION").dt if ev.get("DURATION") else timedelta(hours=1))
        s, e = _local(start, zone), _local(end, zone)
        if e.date() > s.date():  # runs past midnight: keep the part on its own day
            e = datetime.combine(s.date(), time(23, 59))
        if e <= s:
            skip(uid, "zero length")
            continue
        by_uid[uid].append((s, e))
        titles[uid] = str(ev.get("SUMMARY") or "Busy").strip() or "Busy"

    for comp in cal.walk("VEVENT"):
        uid = str(comp.get("UID") or comp.get("SUMMARY") or "")
        if comp.get("RRULE") and uid not in masters:
            masters[uid] = comp

    for uid, slots in by_uid.items():
        title = titles[uid][:255]
        groups: dict[tuple[int, time, time], list[date]] = defaultdict(list)
        for s, e in slots:
            groups[(s.weekday(), s.time().replace(second=0, microsecond=0),
                    e.time().replace(second=0, microsecond=0))].append(s.date())

        master = masters.get(uid)
        for (weekday, st, et), days in groups.items():
            days.sort()
            weekly = (
                master is not None
                and len(days) >= 2
                and all((b - a).days == 7 for a, b in zip(days, days[1:]))
            )
            if weekly:
                result.candidates.append(Candidate(
                    title=title, start_time=st, end_time=et, weekday=weekday,
                    starts_on=days[0], ends_on=_rule_end(master), occurrences=len(days),
                ))
            else:
                for d in days:
                    result.candidates.append(Candidate(
                        title=title, start_time=st, end_time=et, on_date=d,
                    ))

    result.candidates.sort(key=lambda c: (
        c.weekday is None, c.weekday if c.weekday is not None else 0,
        c.on_date or date.min, c.start_time, c.title,
    ))
    if len(result.candidates) > MAX_CANDIDATES:
        result.skipped["over the limit"] += len(result.candidates) - MAX_CANDIDATES
        result.candidates = result.candidates[:MAX_CANDIDATES]
    result.skipped = dict(result.skipped)
    return result
