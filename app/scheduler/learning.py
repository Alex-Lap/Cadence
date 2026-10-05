"""What the weekly check-in learns.

Each course carries an effort multiplier: >1 means its work keeps taking
longer than estimated for this student. It moves toward the observed ratio
(actual / estimated) every time a task is finished, by half the gap -- fast
enough that two or three finished projects make it personal, damped enough
that one bad week doesn't double every estimate.
"""

from __future__ import annotations

from app.scheduler.core import QUANTUM

LEARNING_RATE = 0.5
RATIO_RANGE = (0.25, 4.0)        # ignore absurd entries ("spent 0.1h on a project")
MULTIPLIER_RANGE = (0.5, 2.0)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def update_multiplier(current: float, actual: float, estimated: float) -> float:
    """New multiplier after a task estimated at `estimated` hours took `actual`."""
    if estimated <= 0:
        return current
    ratio = _clamp(actual / estimated, *RATIO_RANGE)
    new = current + LEARNING_RATE * (ratio - current)
    return round(_clamp(new, *MULTIPLIER_RANGE), 3)


def rescale(hours: float, old: float, new: float) -> float:
    """Re-estimate an untouched task when its course's multiplier changes."""
    if old <= 0:
        return hours
    scaled = hours * new / old
    return max(QUANTUM, round(scaled / QUANTUM) * QUANTUM)
