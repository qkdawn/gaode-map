from modules.timeseries.common import (
    build_diverging_cell,
    build_summary_from_counts,
    parse_period,
)


def test_parse_period_accepts_arrow_and_dash_formats():
    assert parse_period("2024-2025", ("2024", "2025", "2026")) == ("2024", "2025")
    assert parse_period("2024 -> 2026", ("2024", "2025", "2026")) == ("2024", "2026")


def test_parse_period_rejects_reversed_range():
    try:
        parse_period("2026-2024", ("2024", "2025", "2026"))
    except ValueError as exc:
        assert "earlier" in str(exc)
    else:
        raise AssertionError("expected parse_period to reject reversed ranges")


def test_build_diverging_cell_marks_rate_drop_as_strong_decrease():
    key, label, color, opacity = build_diverging_cell(-10.0, -0.35, "population_rate")

    assert key == "strong_decrease"
    assert "涓嬮檷" in label
    assert color == "#1d4ed8"
    assert opacity > 0.7


def test_build_summary_from_counts_aggregates_core_stats():
    summary = build_summary_from_counts(
        [
            {"class_key": "increase", "delta": 10.0, "rate": 0.2},
            {"class_key": "decrease", "delta": -5.0, "rate": -0.1},
            {"class_key": "stable", "delta": 0.0, "rate": 0.0},
        ]
    )

    assert summary["cell_count"] == 3
    assert summary["increase_count"] == 1
    assert summary["decrease_count"] == 1
    assert summary["stable_count"] == 1
    assert summary["total_delta"] == 5.0
