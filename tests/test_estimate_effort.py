"""clamp_to_budget is pure arithmetic -- no LLM, no network."""

import pytest

from app.agent.tools.estimate_effort import BAND_HIGH, clamp_to_budget


def test_total_matches_budget():
    raw = {"A": 5, "B": 5, "C": 5}
    out = clamp_to_budget(raw, {"A": 0.5, "B": 0.3, "C": 0.2}, 90)
    assert sum(out.values()) == pytest.approx(90, abs=0.75)


def test_weight_drives_allocation():
    """Equal raw estimates, unequal weights -> heavier item gets more hours."""
    out = clamp_to_budget({"big": 10, "small": 10}, {"big": 0.4, "small": 0.1}, 100)
    assert out["big"] > out["small"]


def test_absurd_estimate_is_pulled_down():
    """A 200-hour guess on a 10% assignment cannot survive the band."""
    out = clamp_to_budget({"sane": 20, "absurd": 200}, {"sane": 0.5, "absurd": 0.1}, 90)
    implied = 90 * (0.1 / 0.6)
    assert out["absurd"] <= implied * BAND_HIGH * 1.5


def test_unweighted_items_get_an_even_share():
    out = clamp_to_budget({"A": 1, "B": 1}, {"A": None, "B": None}, 40)
    assert out["A"] == pytest.approx(out["B"])
    assert sum(out.values()) == pytest.approx(40, abs=0.5)


def test_hours_land_on_quarter_hours():
    out = clamp_to_budget({"A": 3.7, "B": 9.1}, {"A": 0.3, "B": 0.7}, 63)
    for hours in out.values():
        assert (hours * 4) % 1 == 0


def test_empty_input():
    assert clamp_to_budget({}, {}, 90) == {}

def test_budget_scales_to_covered_weight():
    """CIS 6307: five projects at 10% each cover half the grade, so they should
    consume about half a 3-credit term budget (90h), not all of it.

    Mirrors the real bug -- categories were filtered out of the estimate but the
    budget stayed at 100%, doubling every project.
    """
    from app.agent.tools.estimate_effort import HOURS_PER_CREDIT

    titles = [f"Project {i}" for i in range(1, 6)]
    weights = {t: 0.1 for t in titles}
    covered = sum(weights.values())          # 0.5
    budget = 3.0 * HOURS_PER_CREDIT * covered

    out = clamp_to_budget({t: 17.0 for t in titles}, weights, budget)
    assert sum(out.values()) == pytest.approx(45, abs=1.0)
    for hours in out.values():
        assert 7 <= hours <= 11
