"""SQL validation, parsing, and safe query execution against DuckDB files.

Provides functions to validate SQL statements as safe read-only SELECTs,
execute queries with enforced timeouts and row limits, retrieve query
execution plans, and parse/print SQL for round-trip correctness.

All DuckDB connections are opened in read-only mode and managed via
context managers to guarantee cleanup on all code paths.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
import sqlglot.errors
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_ROWS: int = 10_000
DEFAULT_TIMEOUT_SECONDS: float = 30.0

# Keywords that sqlglot cannot reliably parse or that map to exp.Command.
# We reject these before parsing to avoid false-accepts.
_DANGEROUS_KEYWORD_PREFIXES: set[str] = {
    "TRUNCATE",
    "EXPORT",
    "ATTACH",
    "COPY",
    "IMPORT",
    "LOAD",
}

# Expression types that represent DDL statements
_DDL_TYPES: tuple[type, ...] = (exp.Create, exp.Alter, exp.Drop)

# Expression types that represent DML statements
_DML_TYPES: tuple[type, ...] = (exp.Insert, exp.Update, exp.Delete, exp.Merge)

# Regex to strip file-system paths from error messages
_PATH_PATTERN = re.compile(r"(/[^\s:\"']+|[A-Z]:\\[^\s:\"']+)")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    """Structured result from a SQL query execution."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float
    query: str
    truncated: bool = False


@dataclass
class QueryError:
    """Structured error from a failed query."""

    error_type: str  # "validation", "timeout", "execution", "file_not_found"
    message: str
    query: str | None = None
    elapsed_ms: float | None = None


@dataclass
class SQLParseResult:
    """Structured representation of a parsed SQL SELECT statement."""

    select_columns: list[str]
    from_tables: list[str]
    where_clause: str | None
    group_by: list[str]
    order_by: list[str]
    limit: int | None
    has_cte: bool
    has_subquery: bool
    raw_ast: Any  # sqlglot Expression tree


# ---------------------------------------------------------------------------
# SQL Validation
# ---------------------------------------------------------------------------


def validate_sql(sql: str) -> QueryError | None:
    """Validate that *sql* is a single, safe SELECT statement.

    Returns ``None`` on success, ``QueryError`` on failure.

    Strategy:
    1. Keyword pre-screen – reject statements that sqlglot parses as
       ``exp.Command`` (TRUNCATE, EXPORT, ATTACH, COPY, IMPORT, LOAD).
    2. Parse with sqlglot (dialect=duckdb).  Catch ``ParseError``.
    3. Reject multi-statement input (more than one parsed expression).
    4. Allow only ``exp.Select``; reject everything else.
    """
    if not sql or not sql.strip():
        return QueryError(
            error_type="validation",
            message="Empty SQL statement",
            query=sql,
        )

    # --- Step 1: keyword pre-screen ---
    stripped = sql.strip().upper()
    first_word = stripped.split()[0] if stripped.split() else ""
    if first_word in _DANGEROUS_KEYWORD_PREFIXES:
        return QueryError(
            error_type="validation",
            message=f"{first_word} statements are not allowed",
            query=sql,
        )

    # --- Step 2: parse with sqlglot ---
    try:
        expressions = sqlglot.parse(sql, dialect="duckdb")
    except sqlglot.errors.ParseError as exc:
        return QueryError(
            error_type="validation",
            message=f"SQL parse error: {exc}",
            query=sql,
        )

    # Filter out None entries (trailing semicolons produce None)
    expressions = [e for e in expressions if e is not None]

    if not expressions:
        return QueryError(
            error_type="validation",
            message="No valid SQL expression found",
            query=sql,
        )

    # --- Step 3: reject multi-statement ---
    if len(expressions) > 1:
        return QueryError(
            error_type="validation",
            message="Only single SQL statements are allowed",
            query=sql,
        )

    expr = expressions[0]

    # --- Step 4: type check – only SELECT allowed ---
    if isinstance(expr, _DDL_TYPES):
        kind = type(expr).__name__.upper()
        return QueryError(
            error_type="validation",
            message=f"DDL statements ({kind}) are not allowed",
            query=sql,
        )

    if isinstance(expr, _DML_TYPES):
        kind = type(expr).__name__.upper()
        return QueryError(
            error_type="validation",
            message=f"DML statements ({kind}) are not allowed",
            query=sql,
        )

    if isinstance(expr, exp.Command):
        cmd_name = expr.this if isinstance(expr.this, str) else str(expr.this)
        return QueryError(
            error_type="validation",
            message=f"{cmd_name.upper()} statements are not allowed",
            query=sql,
        )

    if not isinstance(expr, exp.Select):
        kind = type(expr).__name__.upper()
        return QueryError(
            error_type="validation",
            message=f"Only SELECT statements are allowed; got {kind}",
            query=sql,
        )

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_error(message: str) -> str:
    """Remove file-system paths from an error message."""
    return _PATH_PATTERN.sub("<path>", message)


# ---------------------------------------------------------------------------
# Query Execution
# ---------------------------------------------------------------------------


def execute_query(
    duckdb_path: str,
    sql: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> QueryResult | QueryError:
    """Validate and execute a SQL query against a DuckDB file.

    Opens a read-only connection, enforces timeout and row limit.
    The connection is closed after execution regardless of outcome.
    """
    # Validate first – no DB connection opened on failure
    validation_error = validate_sql(sql)
    if validation_error is not None:
        return validation_error

    # Check file exists
    if not Path(duckdb_path).exists():
        return QueryError(
            error_type="file_not_found",
            message="Database file not found",
            query=sql,
        )

    conn: duckdb.DuckDBPyConnection | None = None
    timer: threading.Timer | None = None
    start = time.monotonic()

    try:
        conn = duckdb.connect(duckdb_path, read_only=True)

        # Set up timeout via threading – interrupt the connection after deadline
        def _interrupt() -> None:
            with contextlib.suppress(Exception):
                conn.interrupt()  # type: ignore[union-attr]

        timer = threading.Timer(timeout_seconds, _interrupt)
        timer.start()

        # Wrap query to enforce row limit.  Fetch max_rows + 1 so we can
        # detect truncation.
        wrapped_sql = f"SELECT * FROM ({sql}) AS _q LIMIT {max_rows + 1}"
        result = conn.execute(wrapped_sql)
        columns = [desc[0] for desc in result.description]
        all_rows = result.fetchall()

        elapsed_ms = (time.monotonic() - start) * 1000.0

        truncated = len(all_rows) > max_rows
        rows = [list(r) for r in all_rows[:max_rows]]

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=round(elapsed_ms, 2),
            query=sql,
            truncated=truncated,
        )

    except duckdb.InterruptException:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return QueryError(
            error_type="timeout",
            message=f"Query timed out after {timeout_seconds}s",
            query=sql,
            elapsed_ms=round(elapsed_ms, 2),
        )
    except duckdb.CatalogException as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        msg = str(exc)
        # Extract table name from DuckDB error if possible
        table_match = re.search(r"Table with name (\S+) does not exist", msg)
        if table_match:
            table_name = table_match.group(1)
            return QueryError(
                error_type="execution",
                message=f"Table '{table_name}' does not exist",
                query=sql,
                elapsed_ms=round(elapsed_ms, 2),
            )
        return QueryError(
            error_type="execution",
            message=_sanitize_error(msg),
            query=sql,
            elapsed_ms=round(elapsed_ms, 2),
        )
    except duckdb.IOException:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return QueryError(
            error_type="execution",
            message="Could not open database file",
            query=sql,
            elapsed_ms=round(elapsed_ms, 2),
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return QueryError(
            error_type="execution",
            message=_sanitize_error(str(exc)),
            query=sql,
            elapsed_ms=round(elapsed_ms, 2),
        )
    finally:
        if timer is not None:
            timer.cancel()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


# ---------------------------------------------------------------------------
# Query Explanation
# ---------------------------------------------------------------------------


def explain_query(
    duckdb_path: str,
    sql: str,
) -> str | QueryError:
    """Return the DuckDB EXPLAIN output for a query.

    Validates the SQL first; returns ``QueryError`` if invalid.
    """
    validation_error = validate_sql(sql)
    if validation_error is not None:
        return validation_error

    if not Path(duckdb_path).exists():
        return QueryError(
            error_type="file_not_found",
            message="Database file not found",
            query=sql,
        )

    conn: duckdb.DuckDBPyConnection | None = None
    try:
        conn = duckdb.connect(duckdb_path, read_only=True)
        result = conn.execute(f"EXPLAIN {sql}")
        rows = result.fetchall()
        # DuckDB EXPLAIN returns rows of text; join them
        explain_text = "\n".join(str(row[1]) if len(row) > 1 else str(row[0]) for row in rows)
        return explain_text
    except duckdb.CatalogException as exc:
        msg = str(exc)
        table_match = re.search(r"Table with name (\S+) does not exist", msg)
        if table_match:
            table_name = table_match.group(1)
            return QueryError(
                error_type="execution",
                message=f"Table '{table_name}' does not exist",
                query=sql,
            )
        return QueryError(
            error_type="execution",
            message=_sanitize_error(msg),
            query=sql,
        )
    except Exception as exc:
        return QueryError(
            error_type="execution",
            message=_sanitize_error(str(exc)),
            query=sql,
        )
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


# ---------------------------------------------------------------------------
# SQL Parsing and Printing
# ---------------------------------------------------------------------------


def _extract_columns(ast: exp.Expression) -> list[str]:
    """Extract unique column references from the AST."""
    columns: list[str] = []
    seen: set[str] = set()
    for col_expr in ast.find_all(exp.Column):
        col_sql = col_expr.sql(dialect="duckdb")
        if col_sql not in seen:
            seen.add(col_sql)
            columns.append(col_sql)
    return columns


def _extract_tables(ast: exp.Expression) -> list[str]:
    """Extract unique table names from the AST."""
    tables: list[str] = []
    seen: set[str] = set()
    for table_expr in ast.find_all(exp.Table):
        name = table_expr.name
        if name and name != "_q" and name not in seen:
            seen.add(name)
            tables.append(name)
    return tables


def _extract_where(ast: exp.Expression) -> str | None:
    """Extract the WHERE clause text, or None."""
    where_node = ast.find(exp.Where)
    if where_node is None:
        return None
    return where_node.this.sql(dialect="duckdb")


def _extract_group_by(ast: exp.Expression) -> list[str]:
    """Extract GROUP BY column expressions."""
    group_node = ast.find(exp.Group)
    if group_node is None:
        return []
    return [g.sql(dialect="duckdb") for g in group_node.expressions]


def _extract_order_by(ast: exp.Expression) -> list[str]:
    """Extract ORDER BY column expressions."""
    order_node = ast.find(exp.Order)
    if order_node is None:
        return []
    return [
        o.sql(dialect="duckdb") for o in order_node.expressions
    ]


def _extract_limit(ast: exp.Expression) -> int | None:
    """Extract the LIMIT value, or None."""
    limit_node = ast.find(exp.Limit)
    if limit_node is None or limit_node.expression is None:
        return None
    try:
        return int(limit_node.expression.this)
    except (ValueError, TypeError, AttributeError):
        return None


def parse_sql(sql: str) -> SQLParseResult | QueryError:
    """Parse a SQL SELECT into a structured representation.

    Uses sqlglot to extract columns, tables, where clause, group by,
    order by, limit, CTE and subquery flags, and the raw AST.
    """
    validation_error = validate_sql(sql)
    if validation_error is not None:
        return validation_error

    try:
        expressions = sqlglot.parse(sql, dialect="duckdb")
        expressions = [e for e in expressions if e is not None]
        ast: exp.Expression = expressions[0]  # type: ignore[assignment]
    except Exception as parse_exc:
        return QueryError(
            error_type="validation",
            message=f"SQL parse error: {parse_exc}",
            query=sql,
        )

    # Extract SELECT columns
    select_columns: list[str] = _extract_columns(ast)

    # Extract FROM tables
    from_tables: list[str] = _extract_tables(ast)

    # Extract WHERE clause
    where_clause = _extract_where(ast)

    # Extract GROUP BY
    group_by = _extract_group_by(ast)

    # Extract ORDER BY
    order_by = _extract_order_by(ast)

    # Extract LIMIT
    limit_val = _extract_limit(ast)

    # Detect CTE (WITH clause)
    has_cte = bool(ast.find(exp.CTE))

    # Detect subqueries
    has_subquery = bool(ast.find(exp.Subquery))

    return SQLParseResult(
        select_columns=select_columns,
        from_tables=from_tables,
        where_clause=where_clause,
        group_by=group_by,
        order_by=order_by,
        limit=limit_val,
        has_cte=has_cte,
        has_subquery=has_subquery,
        raw_ast=ast,
    )


def print_sql(parsed: SQLParseResult) -> str:
    """Format a structured SQL representation back into a SQL string.

    Uses the raw AST stored in the parse result to regenerate SQL
    in the DuckDB dialect.
    """
    return parsed.raw_ast.sql(dialect="duckdb")
