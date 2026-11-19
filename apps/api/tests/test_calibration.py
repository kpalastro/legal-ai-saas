from __future__ import annotations

import pytest

from scripts.calibrate import summarise


def test_summarise_coverage_and_scores() -> None:
    rows = [
        {"predicted_lower": 80, "predicted_point": 90, "predicted_upper": 100, "outcome": 1},
        {"predicted_lower": 80, "predicted_point": 90, "predicted_upper": 100, "outcome": 0},
        {"predicted_lower": 0, "predicted_point": 10, "predicted_upper": 20, "outcome": 0},
    ]
    report = summarise(rows)
    assert report["n"] == 3
    assert report["range_coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert report["mean_interval_width"] == pytest.approx(20.0)
    assert report["brier_score"] > 0
    assert report["point_mae"] > 0


def test_summarise_rejects_empty() -> None:
    with pytest.raises(ValueError):
        summarise([])
