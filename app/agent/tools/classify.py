"""Spot graded items that involve no work to schedule."""

from __future__ import annotations

import re

# Graded by showing up or speaking up: there's no study time to plan and no due
# date to ask for. The model is asked to flag these too; this catches the ones
# it misses, since a stray "Attendance -- needs a date" prompt is pure noise.
_PARTICIPATION = re.compile(
    r"\b(attendance|participation|class engagement|engagement|in[- ]class activit(y|ies)|clickers?|iclicker)\b",
    re.IGNORECASE,
)


def is_participation_title(title: str) -> bool:
    return bool(_PARTICIPATION.search(title or ""))
