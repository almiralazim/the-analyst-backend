"""Pre-built analytical functions for The Analyst pipeline.

Provides high-level analytics operations — summary statistics, time series
aggregation, segmentation, correlation, anomaly detection, and top-N
analysis — that build SQL queries and delegate execution to sql_helpers.

Each function accepts a DuckDB file path and table/column parameters,
constructs the appropriate SQL, and returns structured result objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.helpers.sql_helpers import QueryError, execute_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SEGMENTS: int = 50
MIN_ANOMALY_POINTS: int = 10
MIN_CORRELATION_PAIRS: int = 3
ANOMALY_SIGMA_THRESHOLD: float = 2.0

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class SummaryStats:
    """Descriptive statistics for a single column."""

    column: str
    is_numeric: bool
    count: int
    null_count: int
    # Numeric fields (None for non-numeric)
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min_val: float | None = None
    max_val: float | None = None
    p25: float | None = None
    p75: float | None = None
    # Categorical fields (None for numeric)
    unique_count: int | None = None
    top_values: list[dict[str, Any]] | None = None


@dataclass
class TimeSeriesPoint:
    """A single point in a time series aggregation."""

    period: str
    value: float
    row_count: int


@dataclass
class SegmentResult:
    """Aggregation result for a single segment."""

    segment: str
    sum_value: float
    mean_value: float
    count: int
    share_pct: float


@dataclass
class AnomalyPoint:
    """A detected anomaly in a time series."""

    date: str
    actual: float
    expected: float
    deviation_sigma: float
    direction: str  # "above" or "below"


@dataclass
class TopNGroup:
    """A single group in a top-N analysis."""

    group: str
    metric_value: float
    row_count: int
    share_pct: float


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

_NUMERIC_TYPE_PREFIXES = (
    "integer", "int", "bigint", "smallint", "tinyint", "hugeint",
    "float", "double", "real", "decimal", "numeric",
    "ubigint", "usmallint", "utinyint", "uinteger", "uhugeint",
)


def _is_numeric_type(type_str: str) -> bool:
    """Determine if a DuckDB type string represents a numeric type."""
    lower = type_str.lower().strip()
    return any(lower.startswith(prefix) for prefix in _NUMERIC_TYPE_PREFIXES)


def _get_column_type(
    duckdb_path: str, table_name: str, column: str
) -> str | QueryError:
    """Query the type of a single column. Returns the type string or QueryError."""
    sql = f'SELECT typeof("{column}") FROM "{table_name}" LIMIT 1'
    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result
    if result.row_count == 0:
        return "VARCHAR"
    return str(result.rows[0][0])


# ---------------------------------------------------------------------------
# compute_summary_stats
# ---------------------------------------------------------------------------


def _safe_int(val: Any) -> int:
    return int(val) if val is not None else 0


def _safe_float(val: Any) -> float | None:
    return float(val) if val is not None else None


def _compute_numeric_stats(
    duckdb_path: str, table_name: str, col: str,
) -> SummaryStats | QueryError:
    """Compute descriptive stats for a numeric column."""
    sql = (
        f'SELECT '
        f'COUNT("{col}"), '
        f'COUNT(*) - COUNT("{col}"), '
        f'AVG("{col}"), '
        f'MEDIAN("{col}"), '
        f'STDDEV_SAMP("{col}"), '
        f'MIN("{col}"), '
        f'MAX("{col}"), '
        f'QUANTILE_CONT("{col}", 0.25), '
        f'QUANTILE_CONT("{col}", 0.75) '
        f'FROM "{table_name}"'
    )
    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result
    row = result.rows[0]
    return SummaryStats(
        column=col,
        is_numeric=True,
        count=_safe_int(row[0]),
        null_count=_safe_int(row[1]),
        mean=_safe_float(row[2]),
        median=_safe_float(row[3]),
        std=_safe_float(row[4]),
        min_val=_safe_float(row[5]),
        max_val=_safe_float(row[6]),
        p25=_safe_float(row[7]),
        p75=_safe_float(row[8]),
    )


def _compute_categorical_stats(
    duckdb_path: str, table_name: str, col: str,
) -> SummaryStats | QueryError:
    """Compute descriptive stats for a non-numeric column."""
    sql = (
        f'SELECT '
        f'COUNT("{col}"), '
        f'COUNT(*) - COUNT("{col}"), '
        f'COUNT(DISTINCT "{col}") '
        f'FROM "{table_name}"'
    )
    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result
    row = result.rows[0]

    top_sql = (
        f'SELECT "{col}", COUNT(*) AS freq '
        f'FROM "{table_name}" '
        f'GROUP BY "{col}" '
        f'ORDER BY COUNT(*) DESC '
        f'LIMIT 10'
    )
    top_result = execute_query(duckdb_path, top_sql)
    if isinstance(top_result, QueryError):
        return top_result

    return SummaryStats(
        column=col,
        is_numeric=False,
        count=_safe_int(row[0]),
        null_count=_safe_int(row[1]),
        unique_count=_safe_int(row[2]),
        top_values=[{"value": r[0], "count": int(r[1])} for r in top_result.rows],
    )


def compute_summary_stats(
    duckdb_path: str,
    table_name: str,
    columns: list[str],
) -> list[SummaryStats] | QueryError:
    """Compute descriptive statistics for specified columns."""
    stats_list: list[SummaryStats] = []

    for col in columns:
        col_type = _get_column_type(duckdb_path, table_name, col)
        if isinstance(col_type, QueryError):
            return col_type

        if _is_numeric_type(col_type):
            stats = _compute_numeric_stats(duckdb_path, table_name, col)
        else:
            stats = _compute_categorical_stats(duckdb_path, table_name, col)

        if isinstance(stats, QueryError):
            return stats
        stats_list.append(stats)

    return stats_list


# ---------------------------------------------------------------------------
# compute_time_series
# ---------------------------------------------------------------------------


def compute_time_series(
    duckdb_path: str,
    table_name: str,
    date_column: str,
    metric_column: str,
    granularity: str,
) -> list[TimeSeriesPoint] | QueryError:
    """Aggregate a metric over time at the specified granularity.

    Supported granularities: day, week, month, quarter, year.
    """
    valid_granularities = ("day", "week", "month", "quarter", "year")
    if granularity.lower() not in valid_granularities:
        return QueryError(
            error_type="validation",
            message=f"Invalid granularity '{granularity}'. Must be one of: {', '.join(valid_granularities)}",
        )

    # Validate date column type
    col_type = _get_column_type(duckdb_path, table_name, date_column)
    if isinstance(col_type, QueryError):
        return col_type

    lower_type = col_type.lower()
    if not any(t in lower_type for t in ("date", "timestamp", "time")):
        return QueryError(
            error_type="validation",
            message=f"Column \"{date_column}\" is not a date/timestamp type (got {col_type})",
        )

    gran = granularity.lower()
    sql = (
        f"SELECT DATE_TRUNC('{gran}', \"{date_column}\") AS period, "
        f'SUM("{metric_column}") AS value, '
        f"COUNT(*) AS row_count "
        f'FROM "{table_name}" '
        f"GROUP BY period "
        f"ORDER BY period"
    )

    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result

    points: list[TimeSeriesPoint] = []
    for row in result.rows:
        period_val = row[0]
        period_str = str(period_val) if period_val is not None else ""
        value = float(row[1]) if row[1] is not None else 0.0
        row_count = int(row[2]) if row[2] is not None else 0
        points.append(TimeSeriesPoint(
            period=period_str,
            value=value,
            row_count=row_count,
        ))

    return points


# ---------------------------------------------------------------------------
# compute_segmentation
# ---------------------------------------------------------------------------


def _build_segmentation_sql(
    table_name: str, segment_column: str, metric_column: str, capped: bool,
) -> str:
    """Build segmentation SQL, optionally capping at MAX_SEGMENTS."""
    if not capped:
        return (
            f'SELECT "{segment_column}" AS segment, '
            f'SUM("{metric_column}") AS sum_value, '
            f'AVG("{metric_column}") AS mean_value, '
            f"COUNT(*) AS count "
            f'FROM "{table_name}" '
            f'GROUP BY "{segment_column}" '
            f"ORDER BY sum_value DESC"
        )
    return (
        f"WITH ranked AS ("
        f"SELECT \"{segment_column}\" AS segment, "
        f"SUM(\"{metric_column}\") AS sum_value, "
        f"AVG(\"{metric_column}\") AS mean_value, "
        f"COUNT(*) AS count "
        f"FROM \"{table_name}\" "
        f"GROUP BY \"{segment_column}\" "
        f"ORDER BY sum_value DESC"
        f"), "
        f"with_rank AS ("
        f"SELECT segment, sum_value, mean_value, count, "
        f"ROW_NUMBER() OVER (ORDER BY sum_value DESC) AS rn "
        f"FROM ranked"
        f") "
        f"SELECT "
        f"CASE WHEN rn <= {MAX_SEGMENTS} THEN segment ELSE 'Other' END AS segment, "
        f"SUM(sum_value) AS sum_value, "
        f"AVG(mean_value) AS mean_value, "
        f"SUM(count) AS count "
        f"FROM with_rank "
        f"GROUP BY CASE WHEN rn <= {MAX_SEGMENTS} THEN segment ELSE 'Other' END "
        f"ORDER BY sum_value DESC"
    )


def compute_segmentation(
    duckdb_path: str,
    table_name: str,
    segment_column: str,
    metric_column: str,
) -> list[SegmentResult] | QueryError:
    """Break down a metric by a categorical dimension."""
    count_sql = f'SELECT COUNT(DISTINCT "{segment_column}") FROM "{table_name}"'
    count_result = execute_query(duckdb_path, count_sql)
    if isinstance(count_result, QueryError):
        return count_result

    distinct_count = _safe_int(count_result.rows[0][0])
    sql = _build_segmentation_sql(
        table_name, segment_column, metric_column, distinct_count > MAX_SEGMENTS,
    )

    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result

    total_sum = sum(_safe_float(row[1]) or 0.0 for row in result.rows)

    segments: list[SegmentResult] = []
    for row in result.rows:
        sum_val = _safe_float(row[1]) or 0.0
        share = (sum_val / total_sum * 100.0) if total_sum != 0 else 0.0
        segments.append(SegmentResult(
            segment=str(row[0]) if row[0] is not None else "NULL",
            sum_value=sum_val,
            mean_value=_safe_float(row[2]) or 0.0,
            count=_safe_int(row[3]),
            share_pct=round(share, 2),
        ))

    return segments


# ---------------------------------------------------------------------------
# compute_correlation
# ---------------------------------------------------------------------------


def compute_correlation(
    duckdb_path: str,
    table_name: str,
    column_a: str,
    column_b: str,
) -> dict[str, Any] | QueryError:
    """Compute Pearson correlation between two numeric columns.

    Excludes rows where either column is NULL.
    Returns insufficient data if fewer than MIN_CORRELATION_PAIRS pairs exist.
    """
    # Validate both columns are numeric
    type_a = _get_column_type(duckdb_path, table_name, column_a)
    if isinstance(type_a, QueryError):
        return type_a
    if not _is_numeric_type(type_a):
        return QueryError(
            error_type="validation",
            message=f"Column \"{column_a}\" is not numeric (type: {type_a})",
        )

    type_b = _get_column_type(duckdb_path, table_name, column_b)
    if isinstance(type_b, QueryError):
        return type_b
    if not _is_numeric_type(type_b):
        return QueryError(
            error_type="validation",
            message=f"Column \"{column_b}\" is not numeric (type: {type_b})",
        )

    sql = (
        f'SELECT CORR("{column_a}", "{column_b}") AS correlation, '
        f"COUNT(*) AS pair_count "
        f'FROM "{table_name}" '
        f'WHERE "{column_a}" IS NOT NULL AND "{column_b}" IS NOT NULL'
    )

    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result

    row = result.rows[0]
    pair_count = int(row[1]) if row[1] is not None else 0

    if pair_count < MIN_CORRELATION_PAIRS:
        return QueryError(
            error_type="execution",
            message=f"Insufficient data: only {pair_count} non-null pairs (minimum {MIN_CORRELATION_PAIRS} required)",
        )

    correlation = float(row[0]) if row[0] is not None else None

    return {
        "correlation": correlation,
        "pair_count": pair_count,
        "column_a": column_a,
        "column_b": column_b,
    }


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------


def detect_anomalies(
    duckdb_path: str,
    table_name: str,
    date_column: str,
    metric_column: str,
) -> list[AnomalyPoint] | QueryError:
    """Detect statistical anomalies (>2σ) in a daily time series.

    Computes mean and stddev over the full series, then flags points
    where |actual - mean| > ANOMALY_SIGMA_THRESHOLD * stddev.
    """
    # Compute daily time series
    ts_result = compute_time_series(
        duckdb_path, table_name, date_column, metric_column, "day"
    )
    if isinstance(ts_result, QueryError):
        return ts_result

    if len(ts_result) < MIN_ANOMALY_POINTS:
        return QueryError(
            error_type="execution",
            message=f"Insufficient data: only {len(ts_result)} data points (minimum {MIN_ANOMALY_POINTS} required)",
        )

    # Compute mean and stddev from the time series values
    values = [p.value for p in ts_result]
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    stddev = variance ** 0.5

    if stddev == 0:
        # No variance means no anomalies
        return []

    anomalies: list[AnomalyPoint] = []
    for point in ts_result:
        deviation = abs(point.value - mean)
        if deviation > ANOMALY_SIGMA_THRESHOLD * stddev:
            sigma_count = deviation / stddev
            direction = "above" if point.value > mean else "below"
            anomalies.append(AnomalyPoint(
                date=point.period,
                actual=point.value,
                expected=round(mean, 4),
                deviation_sigma=round(sigma_count, 4),
                direction=direction,
            ))

    return anomalies


# ---------------------------------------------------------------------------
# compute_top_n
# ---------------------------------------------------------------------------


def compute_top_n(
    duckdb_path: str,
    table_name: str,
    group_column: str,
    metric_column: str,
    n: int = 10,
) -> list[TopNGroup] | QueryError:
    """Retrieve the top N groups by aggregated metric value.

    Returns at most N groups ordered by descending SUM of the metric column,
    each with metric_value, row_count, and share_pct.
    """
    # Get total metric sum for share_pct calculation
    total_sql = f'SELECT SUM("{metric_column}") FROM "{table_name}"'
    total_result = execute_query(duckdb_path, total_sql)
    if isinstance(total_result, QueryError):
        return total_result

    total_sum = float(total_result.rows[0][0]) if total_result.rows[0][0] is not None else 0.0

    # Get top N groups
    sql = (
        f'SELECT "{group_column}" AS group_name, '
        f'SUM("{metric_column}") AS metric_value, '
        f"COUNT(*) AS row_count "
        f'FROM "{table_name}" '
        f'GROUP BY "{group_column}" '
        f"ORDER BY metric_value DESC "
        f"LIMIT {n}"
    )

    result = execute_query(duckdb_path, sql)
    if isinstance(result, QueryError):
        return result

    groups: list[TopNGroup] = []
    for row in result.rows:
        group_name = str(row[0]) if row[0] is not None else "NULL"
        metric_value = float(row[1]) if row[1] is not None else 0.0
        row_count = int(row[2]) if row[2] is not None else 0
        share = (metric_value / total_sum * 100.0) if total_sum != 0 else 0.0

        groups.append(TopNGroup(
            group=group_name,
            metric_value=metric_value,
            row_count=row_count,
            share_pct=round(share, 2),
        ))

    return groups
