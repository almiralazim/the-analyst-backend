"""File processing service: parse CSV/Excel, load into DuckDB, profile schema."""

from __future__ import annotations

import uuid
from pathlib import Path

import chardet
import duckdb
import pandas as pd


def process_dataset_files(
    dataset_id: uuid.UUID,
    file_paths: list[str],
    storage_root: Path,
) -> dict:
    """Parse uploaded files, load into DuckDB, and profile the schema.

    Returns:
        dict with keys: duckdb_path, schema_profile, table_count, total_rows
    """
    dataset_dir = storage_root / str(dataset_id)
    duckdb_path = str(dataset_dir / "data.duckdb")

    conn = duckdb.connect(duckdb_path)
    tables = []

    try:
        for file_path in file_paths:
            path = Path(file_path)
            ext = path.suffix.lower()

            if ext in (".csv", ".tsv"):
                df = _parse_csv(path, delimiter="\t" if ext == ".tsv" else None)
                table_name = _sanitize_table_name(path.stem)
                _load_dataframe(conn, table_name, df)
                tables.append((table_name, df))

            elif ext in (".xlsx", ".xls"):
                sheets = _parse_excel(path)
                for sheet_name, df in sheets.items():
                    table_name = _sanitize_table_name(sheet_name)
                    _load_dataframe(conn, table_name, df)
                    tables.append((table_name, df))

        # Profile the schema
        schema_profile = _profile_schema(tables)
        total_rows = sum(len(df) for _, df in tables)

    finally:
        conn.close()

    return {
        "duckdb_path": duckdb_path,
        "schema_profile": schema_profile,
        "table_count": len(tables),
        "total_rows": total_rows,
    }


def _parse_csv(path: Path, delimiter: str | None = None) -> pd.DataFrame:
    """Parse a CSV/TSV file with encoding detection."""
    raw = path.read_bytes()
    detected = chardet.detect(raw[:10000])
    encoding = detected.get("encoding", "utf-8") or "utf-8"

    return pd.read_csv(
        path,
        encoding=encoding,
        delimiter=delimiter,
        low_memory=False,
        parse_dates=True,
    )


def _parse_excel(path: Path) -> dict[str, pd.DataFrame]:
    """Parse an Excel file, returning one DataFrame per sheet."""
    engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
    xls = pd.ExcelFile(path, engine=engine)
    sheets = {}
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name)
        if not df.empty:
            sheets[sheet_name] = df
    return sheets


def _sanitize_table_name(name: str) -> str:
    """Convert a filename or sheet name to a valid SQL table name."""
    import re
    clean = re.sub(r"\W", "_", name.lower().strip())
    clean = re.sub(r"_+", "_", clean).strip("_")
    if clean and clean[0].isdigit():
        clean = f"t_{clean}"
    return clean or "unnamed_table"


def _load_dataframe(conn: duckdb.DuckDBPyConnection, table_name: str, df: pd.DataFrame) -> None:
    """Load a pandas DataFrame into a DuckDB table."""
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM df')


def _profile_column(col: pd.Series, col_name: str, row_count: int) -> dict:
    """Build the profile dict for a single column."""
    col_info: dict = {
        "name": col_name,
        "type": _map_dtype(col.dtype),
        "nullable": bool(col.isnull().any()),
        "null_rate": round(float(col.isnull().mean()), 4),
        "unique_count": int(col.nunique()),
    }
    non_null = col.dropna()
    if len(non_null) > 0:
        col_info["sample_values"] = [str(v) for v in non_null.head(5).tolist()]
    if pd.api.types.is_numeric_dtype(col):
        _add_numeric_stats(col_info, col, non_null)
    elif pd.api.types.is_string_dtype(col) and col_info["unique_count"] <= 50:
        vc = col.value_counts().head(20)
        col_info["value_counts"] = {str(k): int(v) for k, v in vc.items()}
    if pd.api.types.is_datetime64_any_dtype(col) and len(non_null) > 0:
        col_info["type"] = "DATE"
        col_info["date_range_days"] = int((non_null.max() - non_null.min()).days)
        col_info["min"] = str(non_null.min().date())
        col_info["max"] = str(non_null.max().date())
    if col_info["unique_count"] == row_count and col_info["null_rate"] == 0:
        col_info["is_primary_key_candidate"] = True
    return col_info


def _add_numeric_stats(col_info: dict, col: pd.Series, non_null: pd.Series) -> None:
    """Add numeric statistics and optional histogram to a column profile."""
    col_info.update({
        "min": _safe_num(col.min()),
        "max": _safe_num(col.max()),
        "mean": _safe_num(col.mean()),
        "median": _safe_num(col.median()),
        "std": _safe_num(col.std()),
    })
    try:
        hist, bin_edges = pd.cut(non_null, bins=10, retbins=True)
        col_info["distribution"] = {
            "histogram": hist.value_counts(sort=False).tolist(),
            "bin_edges": [round(float(b), 4) for b in bin_edges],
        }
    except Exception:
        pass


def _collect_quality_warnings(table_name: str, columns: list[dict]) -> list[dict]:
    """Return data-quality warnings for columns with high null rates."""
    warnings: list[dict] = []
    for c in columns:
        if c["null_rate"] > 0.3:
            warnings.append({
                "table": table_name, "column": c["name"],
                "issue": f"High null rate ({c['null_rate']:.0%})", "severity": "medium",
            })
    return warnings


def _profile_schema(tables: list[tuple[str, pd.DataFrame]]) -> dict:
    """Profile all tables and return the schema_profile JSON structure."""
    profile = {"tables": [], "detected_relationships": [], "data_quality": {"overall_completeness": 1.0, "tables_with_issues": [], "warnings": []}}

    all_columns_by_table: dict[str, list[dict]] = {}

    for table_name, df in tables:
        columns = [_profile_column(df[col_name], col_name, len(df)) for col_name in df.columns]
        profile["tables"].append({"name": table_name, "row_count": len(df), "columns": columns})
        all_columns_by_table[table_name] = columns

        warnings = _collect_quality_warnings(table_name, columns)
        profile["data_quality"]["warnings"].extend(warnings)
        if warnings and table_name not in profile["data_quality"]["tables_with_issues"]:
            profile["data_quality"]["tables_with_issues"].append(table_name)

    # Detect FK relationships
    profile["detected_relationships"] = _detect_relationships(all_columns_by_table, tables)

    # Overall completeness
    total_cells = sum(len(df) * len(df.columns) for _, df in tables)
    total_nulls = sum(df.isnull().sum().sum() for _, df in tables)
    if total_cells > 0:
        profile["data_quality"]["overall_completeness"] = round(1 - total_nulls / total_cells, 4)

    return profile


def _check_column_overlap(
    col_name: str, t1: str, t2: str,
    table_dfs: dict[str, pd.DataFrame],
) -> dict | None:
    """Check if a shared column between two tables qualifies as a FK relationship."""
    df1, df2 = table_dfs[t1], table_dfs[t2]
    if col_name not in df1.columns or col_name not in df2.columns:
        return None
    vals1 = set(df1[col_name].dropna().unique())
    vals2 = set(df2[col_name].dropna().unique())
    if not vals1 or not vals2:
        return None
    overlap = len(vals1 & vals2) / min(len(vals1), len(vals2))
    if overlap < 0.8:
        return None
    from_t, to_t = (t1, t2) if len(vals1) >= len(vals2) else (t2, t1)
    rel_type = "many_to_one" if len(vals1) != len(vals2) else "one_to_one"
    return {
        "from_table": from_t, "from_column": col_name,
        "to_table": to_t, "to_column": col_name,
        "type": rel_type, "match_rate": round(overlap, 4),
    }


def _mark_fk_candidate(columns_by_table: dict, rel: dict) -> None:
    """Mark the from-table column as a foreign key candidate."""
    for c in columns_by_table[rel["from_table"]]:
        if c["name"] == rel["from_column"]:
            c["is_foreign_key_candidate"] = True
            c["references_table"] = rel["to_table"]
            c["references_column"] = rel["to_column"]
            break


def _detect_relationships(columns_by_table: dict, tables: list[tuple[str, pd.DataFrame]]) -> list[dict]:
    """Detect foreign key candidates by matching column names and value overlap."""
    relationships: list[dict] = []
    table_dfs = dict(tables)
    table_names = list(columns_by_table.keys())

    for i, t1 in enumerate(table_names):
        for t2 in table_names[i + 1:]:
            cols1 = {c["name"] for c in columns_by_table[t1]}
            shared = cols1 & {c["name"] for c in columns_by_table[t2]}

            for col_name in shared:
                rel = _check_column_overlap(col_name, t1, t2, table_dfs)
                if rel:
                    relationships.append(rel)
                    _mark_fk_candidate(columns_by_table, rel)

    return relationships


def _map_dtype(dtype) -> str:
    """Map pandas dtype to a SQL-like type string."""
    s = str(dtype)
    if "int" in s:
        return "INTEGER" if "64" not in s else "BIGINT"
    if "float" in s:
        return "DOUBLE"
    if "bool" in s:
        return "BOOLEAN"
    if "datetime" in s:
        return "TIMESTAMP"
    return "VARCHAR"


def _safe_num(val) -> float | None:
    """Safely convert a numeric value, handling NaN/Inf."""
    import math
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    return round(float(val), 4)
