"""Pre-built analytical functions for the AI Analyst pipeline.

Provides high-level analytics operations — summary statistics, time series
aggregation, segmentation, correlation, anomaly detection, and top-N
analysis — that build SQL queries and delegate execution to sql_helpers.

Each function accepts a DuckDB file path and table/column parameters,
constructs the appropriate SQL, and returns structured result objects.
"""
