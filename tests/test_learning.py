from app.scheduler.learning import rescale, update_multiplier


def test_on_estimate_keeps_multiplier():
    assert update_multiplier(1.0, 8, 8) == 1.0


def test_running_long_moves_halfway():
    assert update_multiplier(1.0, 12, 8) == 1.25  # ratio 1.5


def test_running_short_moves_down():
    assert update_multiplier(1.0, 4, 8) == 0.75


def test_absurd_entries_are_clamped():
    assert update_multiplier(1.0, 100, 1) == 2.0
    assert update_multiplier(1.0, 0, 8) == 0.625  # ratio floor 0.25


def test_zero_estimate_is_ignored():
    assert update_multiplier(1.3, 5, 0) == 1.3


def test_rescale_snaps_to_quarter_hours():
    assert rescale(8, 1.0, 1.25) == 10
    assert rescale(3, 1.0, 1.1) == 3.25
    assert rescale(0.25, 1.0, 0.5) == 0.25
