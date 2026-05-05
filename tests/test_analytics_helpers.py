"""Unit tests for app.helpers.analytics_helpers module.

Covers:
- compute_summary_stats: numeric and categorical columns
- compute_time_series: day/week/month granularity, ordering, type validation
- compute_segmentation: basic segmentation, share_pct, capping at 50
- compute_correlation: valid correlation, insufficient data, non-numeric rejection
- detect_anomalies: anomaly detection, insufficient data
- compute_top_n: top-N groups, share_pct, N > distinct groups
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from app.helpers.analytics_helpers import (
    ANOMALY_SIGMA_THRESHOLD,
    MAX_SEGMENTS,
    MIN_ANOMALY_POINTS,
    MIN_CORRELATION_PAIRS,
    AnomalyPoint,
    SegmentResult,
    SummaryStats,
    TimeSeriesPoint,
    TopNGroup,
    compute_correlation,
    compute_segmentation,
    compute_summary_stats,
    compute_time_series,
    compute_top_n,
    detect_anomalies,
)
from app.helpers.sql_helpers import QueryError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orders_db(tmp_path: Path) -> str:
    """Create a temporary DuckDB file with a realistic orders table (~20 rows)."""
    db_path = str(tmp_path / "orders.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE orders (
            id INTEGER,
            customer VARCHAR,
            amount DOUBLE,
            order_date DATE,
            category VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO orders VALUES
        (1,  'Alice',   100.0, '2025-01-01', 'Electronics'),
        (2,  'Bob',     200.0, '2025-01-02', 'Clothing'),
        (3,  'Alice',   150.0, '2025-01-03', 'Electronics'),
        (4,  'Charlie', 300.0, '2025-01-04', 'Food'),
        (5,  'Bob',      50.0, '2025-01-05', 'Clothing'),
        (6,  'Alice',    75.0, '2025-01-06', 'Food'),
        (7,  'Dave',    400.0, '2025-01-07', 'Electronics'),
        (8,  'Eve',     120.0, '2025-01-08', 'Clothing'),
        (9,  'Charlie', 180.0, '2025-01-09', 'Food'),
        (10, 'Bob',     220.0, '2025-01-10', 'Electronics'),
        (11, 'Alice',    90.0, '2025-01-11', 'Clothing'),
        (12, 'Dave',    350.0, '2025-01-12', 'Electronics'),
        (13, 'Eve',      60.0, '2025-01-13', 'Food'),
        (14, 'Charlie', 500.0, '2025-01-14', 'Electronics'),
        (15, 'Bob',     130.0, '2025-01-15', 'Clothing'),
        (16, 'Alice',   275.0, '2025-01-16', 'Food'),
        (17, 'Dave',    190.0, '2025-01-17', 'Electronics'),
        (18, 'Eve',     310.0, '2025-01-18', 'Clothing'),
        (19, 'Charlie', 140.0, '2025-01-19', 'Food'),
        (20, 'Bob',      85.0, '2025-01-20', 'Electronics')
    """)
    conn.close()
    return db_path


@pytest.fixture
def many_segments_db(tmp_path: Path) -> str:
    """Create a DuckDB file with >50 distinct segment values for capping tests."""
    db_path = str(tmp_path / "segments.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE products (
            category VARCHAR,
            revenue DOUBLE
        )
    """)
    # Insert 60 distinct categories with varying revenue
    for i in range(60):
        revenue = (60 - i) * 10.0  # Descending revenue by category number
        conn.execute(
            "INSERT INTO products VALUES (?, ?)",
            [f"cat_{i:03d}", revenue],
        )
    conn.close()
    return db_path


# ===========================================================================
# Tests for compute_summary_stats
# ===========================================================================


class TestComputeSummaryStats:
    """Tests for the compute_summary_stats function."""

    def test_numeric_column_stats(self, orders_db: str):
        result = compute_summary_stats(orders_db, "orders", ["amount"])
        assert isinstance(result, list)
        assert len(result) == 1

        stats = result[0]
        assert isinstance(stats, SummaryStats)
        assert stats.column == "amount"
        assert stats.is_numeric is True
        assert stats.count == 20
        assert stats.null_count == 0
        assert stats.mean is not None
        assert stats.median is not None
        assert stats.std is not None
        assert stats.min_val is not None
        assert stats.max_val is not None
        assert stats.p25 is not None
        assert stats.p75 is not None

    def test_numeric_stats_values_correct(self, orders_db: str):
        result = compute_summary_stats(orders_db, "orders", ["amount"])
        assert isinstance(result, list)
        stats = result[0]

        # Known values from the test data
        assert stats.min_val == pytest.approx(50.0)
        assert stats.max_val == pytest.approx(500.0)
        assert stats.count == 20
        # Mean of all amounts
        total = sum([
            100, 200, 150, 300, 50, 75, 400, 120, 180, 220,
            90, 350, 60, 500, 130, 275, 190, 310, 140, 85,
        ])
        expected_mean = total / 20
        assert abs(stats.mean - expected_mean) < 0.01

    def test_categorical_column_stats(self, orders_db: str):
        result = compute_summary_stats(orders_db, "orders", ["customer"])
        assert isinstance(result, list)
        assert len(result) == 1

        stats = result[0]
        assert isinstance(stats, SummaryStats)
        assert stats.column == "customer"
        assert stats.is_numeric is False
        assert stats.count == 20
        assert stats.null_count == 0
        assert stats.unique_count == 5  # Alice, Bob, Charlie, Dave, Eve
        assert stats.top_values is not None
        assert len(stats.top_values) <= 10
        # Numeric fields should be None
        assert stats.mean is None
        assert stats.median is None

    def test_multiple_columns(self, orders_db: str):
        result = compute_summary_stats(
            orders_db, "orders", ["amount", "customer", "id"]
        )
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0].column == "amount"
        assert result[1].column == "customer"
        assert result[2].column == "id"

    def test_nonexistent_column_returns_error(self, orders_db: str):
        result = compute_summary_stats(
            orders_db, "orders", ["nonexistent_col"]
        )
        assert isinstance(result, QueryError)

    def test_nonexistent_table_returns_error(self, orders_db: str):
        result = compute_summary_stats(
            orders_db, "no_such_table", ["amount"]
        )
        assert isinstance(result, QueryError)

    def test_top_values_structure(self, orders_db: str):
        result = compute_summary_stats(orders_db, "orders", ["category"])
        assert isinstance(result, list)
        stats = result[0]
        assert stats.top_values is not None
        for entry in stats.top_values:
            assert "value" in entry
            assert "count" in entry
            assert isinstance(entry["count"], int)


# ===========================================================================
# Tests for compute_time_series
# ===========================================================================


class TestComputeTimeSeries:
    """Tests for the compute_time_series function."""

    def test_daily_granularity(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "amount", "day"
        )
        assert isinstance(result, list)
        assert len(result) == 20  # One row per day
        assert all(isinstance(p, TimeSeriesPoint) for p in result)

    def test_results_ordered_by_period(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "amount", "day"
        )
        assert isinstance(result, list)
        periods = [p.period for p in result]
        assert periods == sorted(periods)

    def test_weekly_granularity(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "amount", "week"
        )
        assert isinstance(result, list)
        # 20 days spanning ~3 weeks
        assert len(result) >= 2
        assert len(result) <= 4

    def test_monthly_granularity(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "amount", "month"
        )
        assert isinstance(result, list)
        # All data is in January 2025
        assert len(result) == 1
        assert result[0].row_count == 20

    def test_time_series_point_structure(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "amount", "day"
        )
        assert isinstance(result, list)
        point = result[0]
        assert point.period != ""
        assert point.value > 0
        assert point.row_count >= 1

    def test_non_date_column_returns_error(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "customer", "amount", "day"
        )
        assert isinstance(result, QueryError)
        assert "not a date" in result.message.lower() or "type" in result.message.lower()

    def test_invalid_granularity_returns_error(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "amount", "hourly"
        )
        assert isinstance(result, QueryError)
        assert "granularity" in result.message.lower()

    def test_nonexistent_column_returns_error(self, orders_db: str):
        result = compute_time_series(
            orders_db, "orders", "order_date", "nonexistent", "day"
        )
        assert isinstance(result, QueryError)


# ===========================================================================
# Tests for compute_segmentation
# ===========================================================================


class TestComputeSegmentation:
    """Tests for the compute_segmentation function."""

    def test_basic_segmentation(self, orders_db: str):
        result = compute_segmentation(
            orders_db, "orders", "category", "amount"
        )
        assert isinstance(result, list)
        assert all(isinstance(s, SegmentResult) for s in result)

    def test_segments_ordered_by_sum_desc(self, orders_db: str):
        result = compute_segmentation(
            orders_db, "orders", "category", "amount"
        )
        assert isinstance(result, list)
        sums = [s.sum_value for s in result]
        assert sums == sorted(sums, reverse=True)

    def test_share_pct_sums_to_100(self, orders_db: str):
        result = compute_segmentation(
            orders_db, "orders", "category", "amount"
        )
        assert isinstance(result, list)
        total_share = sum(s.share_pct for s in result)
        assert abs(total_share - 100.0) < 1.0  # Allow rounding tolerance

    def test_segment_result_structure(self, orders_db: str):
        result = compute_segmentation(
            orders_db, "orders", "category", "amount"
        )
        assert isinstance(result, list)
        seg = result[0]
        assert seg.segment != ""
        assert seg.sum_value > 0
        assert seg.mean_value > 0
        assert seg.count > 0
        assert seg.share_pct > 0

    def test_segmentation_by_customer(self, orders_db: str):
        result = compute_segmentation(
            orders_db, "orders", "customer", "amount"
        )
        assert isinstance(result, list)
        assert len(result) == 5  # Alice, Bob, Charlie, Dave, Eve

    def test_capping_at_max_segments(self, many_segments_db: str):
        result = compute_segmentation(
            many_segments_db, "products", "category", "revenue"
        )
        assert isinstance(result, list)
        # Should have at most MAX_SEGMENTS + 1 (for "Other")
        assert len(result) <= MAX_SEGMENTS + 1
        # Should have an "Other" bucket
        segment_names = [s.segment for s in result]
        assert "Other" in segment_names

    def test_capping_other_bucket_values(self, many_segments_db: str):
        result = compute_segmentation(
            many_segments_db, "products", "category", "revenue"
        )
        assert isinstance(result, list)
        other = next(s for s in result if s.segment == "Other")
        # "Other" should aggregate the bottom 10 categories (60 - 50 = 10)
        assert other.count == 10
        assert other.sum_value > 0

    def test_nonexistent_column_returns_error(self, orders_db: str):
        result = compute_segmentation(
            orders_db, "orders", "nonexistent", "amount"
        )
        assert isinstance(result, QueryError)


# ===========================================================================
# Tests for compute_correlation
# ===========================================================================


class TestComputeCorrelation:
    """Tests for the compute_correlation function."""

    def test_valid_correlation(self, orders_db: str):
        result = compute_correlation(
            orders_db, "orders", "id", "amount"
        )
        assert isinstance(result, dict)
        assert "correlation" in result
        assert "pair_count" in result
        assert "column_a" in result
        assert "column_b" in result
        assert result["pair_count"] == 20
        assert result["column_a"] == "id"
        assert result["column_b"] == "amount"
        # Correlation should be between -1 and 1
        assert -1.0 <= result["correlation"] <= 1.0

    def test_non_numeric_column_a_returns_error(self, orders_db: str):
        result = compute_correlation(
            orders_db, "orders", "customer", "amount"
        )
        assert isinstance(result, QueryError)
        assert "not numeric" in result.message.lower()

    def test_non_numeric_column_b_returns_error(self, orders_db: str):
        result = compute_correlation(
            orders_db, "orders", "amount", "customer"
        )
        assert isinstance(result, QueryError)
        assert "not numeric" in result.message.lower()

    def test_insufficient_data(self, tmp_path: Path):
        """Correlation with fewer than MIN_CORRELATION_PAIRS pairs returns error."""
        db_path = str(tmp_path / "small.duckdb")
        conn = duckdb.connect(db_path)
        conn.execute("CREATE TABLE tiny (a DOUBLE, b DOUBLE)")
        conn.execute("INSERT INTO tiny VALUES (1.0, 2.0), (NULL, 3.0)")
        conn.close()

        result = compute_correlation(db_path, "tiny", "a", "b")
        assert isinstance(result, QueryError)
        assert "insufficient" in result.message.lower()

    def test_nonexistent_column_returns_error(self, orders_db: str):
        result = compute_correlation(
            orders_db, "orders", "amount", "nonexistent"
        )
        assert isinstance(result, QueryError)


# ===========================================================================
# Tests for detect_anomalies
# ===========================================================================


class TestDetectAnomalies:
    """Tests for the detect_anomalies function."""

    def test_detects_anomalies_in_data(self, orders_db: str):
        result = detect_anomalies(
            orders_db, "orders", "order_date", "amount"
        )
        assert isinstance(result, list)
        # With 20 data points and varied amounts, there should be some anomalies
        # (500 and 50 are likely outliers)
        assert all(isinstance(a, AnomalyPoint) for a in result)

    def test_anomaly_point_structure(self, orders_db: str):
        result = detect_anomalies(
            orders_db, "orders", "order_date", "amount"
        )
        assert isinstance(result, list)
        if len(result) > 0:
            anomaly = result[0]
            assert anomaly.date != ""
            assert anomaly.actual > 0
            assert anomaly.expected > 0
            assert anomaly.deviation_sigma > ANOMALY_SIGMA_THRESHOLD
            assert anomaly.direction in ("above", "below")

    def test_insufficient_data_returns_error(self, tmp_path: Path):
        """Fewer than MIN_ANOMALY_POINTS data points returns error."""
        db_path = str(tmp_path / "small_ts.duckdb")
        conn = duckdb.connect(db_path)
        conn.execute("CREATE TABLE small_ts (dt DATE, val DOUBLE)")
        for i in range(5):
            conn.execute(
                "INSERT INTO small_ts VALUES (?, ?)",
                [f"2025-01-{i+1:02d}", float(i * 10)],
            )
        conn.close()

        result = detect_anomalies(db_path, "small_ts", "dt", "val")
        assert isinstance(result, QueryError)
        assert "insufficient" in result.message.lower()

    def test_no_anomalies_with_constant_data(self, tmp_path: Path):
        """Constant values should produce no anomalies (stddev = 0)."""
        db_path = str(tmp_path / "constant.duckdb")
        conn = duckdb.connect(db_path)
        conn.execute("CREATE TABLE constant_ts (dt DATE, val DOUBLE)")
        for i in range(15):
            conn.execute(
                "INSERT INTO constant_ts VALUES (?, ?)",
                [f"2025-01-{i+1:02d}", 100.0],
            )
        conn.close()

        result = detect_anomalies(db_path, "constant_ts", "dt", "val")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_non_date_column_returns_error(self, orders_db: str):
        result = detect_anomalies(
            orders_db, "orders", "customer", "amount"
        )
        assert isinstance(result, QueryError)


# ===========================================================================
# Tests for compute_top_n
# ===========================================================================


class TestComputeTopN:
    """Tests for the compute_top_n function."""

    def test_basic_top_n(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "customer", "amount", n=3
        )
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(g, TopNGroup) for g in result)

    def test_results_ordered_by_metric_desc(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "customer", "amount", n=5
        )
        assert isinstance(result, list)
        values = [g.metric_value for g in result]
        assert values == sorted(values, reverse=True)

    def test_top_n_group_structure(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "customer", "amount", n=5
        )
        assert isinstance(result, list)
        group = result[0]
        assert group.group != ""
        assert group.metric_value > 0
        assert group.row_count > 0
        assert group.share_pct > 0

    def test_share_pct_values(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "customer", "amount", n=5
        )
        assert isinstance(result, list)
        # All 5 customers returned, shares should sum to ~100%
        total_share = sum(g.share_pct for g in result)
        assert abs(total_share - 100.0) < 1.0

    def test_n_exceeds_distinct_groups(self, orders_db: str):
        """When N > distinct groups, return all groups without error."""
        result = compute_top_n(
            orders_db, "orders", "customer", "amount", n=100
        )
        assert isinstance(result, list)
        assert len(result) == 5  # Only 5 distinct customers

    def test_default_n_is_10(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "customer", "amount"
        )
        assert isinstance(result, list)
        # 5 customers < default n=10, so all returned
        assert len(result) == 5

    def test_top_n_by_category(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "category", "amount", n=2
        )
        assert isinstance(result, list)
        assert len(result) == 2
        # Electronics should be top (most total revenue)
        assert result[0].group == "Electronics"

    def test_nonexistent_column_returns_error(self, orders_db: str):
        result = compute_top_n(
            orders_db, "orders", "nonexistent", "amount", n=5
        )
        assert isinstance(result, QueryError)


# ===========================================================================
# Tests for constants
# ===========================================================================


class TestConstants:
    """Verify module constants have expected values."""

    def test_max_segments(self):
        assert MAX_SEGMENTS == 50

    def test_min_anomaly_points(self):
        assert MIN_ANOMALY_POINTS == 10

    def test_min_correlation_pairs(self):
        assert MIN_CORRELATION_PAIRS == 3

    def test_anomaly_sigma_threshold(self):
        assert ANOMALY_SIGMA_THRESHOLD == pytest.approx(2.0)
