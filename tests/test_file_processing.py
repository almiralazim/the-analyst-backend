"""Tests for file processing: CSV parsing, DuckDB loading, schema profiling."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services.file_processing import (
    _parse_csv,
    _profile_schema,
    _sanitize_table_name,
    process_dataset_files,
)


class TestSanitizeTableName:
    def test_basic_name(self):
        assert _sanitize_table_name("sales") == "sales"

    def test_spaces_and_special_chars(self):
        assert _sanitize_table_name("Q3 Sales Data!") == "q3_sales_data"

    def test_leading_digit(self):
        assert _sanitize_table_name("2025_data") == "t_2025_data"

    def test_empty_string(self):
        assert _sanitize_table_name("") == "unnamed_table"

    def test_multiple_underscores(self):
        assert _sanitize_table_name("sales___data") == "sales_data"


class TestParseCSV:
    def test_parses_simple_csv(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "id,name,value\n1,Alice,100\n2,Bob,200\n3,Charlie,300\n",
            encoding="utf-8",
        )
        df = _parse_csv(csv_file)
        assert len(df) == 3
        assert list(df.columns) == ["id", "name", "value"]

    def test_handles_missing_values(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("id,name,value\n1,Alice,100\n2,,200\n3,Charlie,\n")
        df = _parse_csv(csv_file)
        assert len(df) == 3
        assert df["name"].isnull().sum() == 1


@pytest.mark.asyncio
class TestProcessDatasetFiles:
    async def test_processes_csv_file(self, tmp_path):
        # Create a CSV file
        csv_file = tmp_path / "raw" / "sales.csv"
        csv_file.parent.mkdir(parents=True)
        csv_file.write_text(
            "order_id,customer_id,revenue\n"
            "ORD-001,CUST-001,149.97\n"
            "ORD-002,CUST-002,49.99\n"
            "ORD-003,CUST-001,99.98\n",
            encoding="utf-8",
        )

        dataset_id = uuid.uuid4()
        storage_root = tmp_path
        (storage_root / str(dataset_id)).mkdir()

        result = process_dataset_files(
            dataset_id, [str(csv_file)], storage_root
        )

        assert result["table_count"] == 1
        assert result["total_rows"] == 3
        assert result["duckdb_path"].endswith("data.duckdb")
        assert "tables" in result["schema_profile"]
        assert len(result["schema_profile"]["tables"]) == 1

        # Check schema profile structure
        table = result["schema_profile"]["tables"][0]
        assert table["name"] == "sales"
        assert table["row_count"] == 3
        assert len(table["columns"]) == 3

        # Check column profiling
        revenue_col = next(c for c in table["columns"] if c["name"] == "revenue")
        assert revenue_col["type"] == "DOUBLE"
        assert "min" in revenue_col
        assert "max" in revenue_col
        assert "mean" in revenue_col

    async def test_detects_relationships(self, tmp_path):
        # Create two related CSV files
        orders_file = tmp_path / "raw" / "orders.csv"
        orders_file.parent.mkdir(parents=True)
        orders_file.write_text(
            "order_id,customer_id,amount\n"
            "1,C1,100\n2,C2,200\n3,C1,150\n",
        )

        customers_file = tmp_path / "raw" / "customers.csv"
        customers_file.write_text(
            "customer_id,name,segment\n"
            "C1,Alice,Enterprise\nC2,Bob,Consumer\n",
        )

        dataset_id = uuid.uuid4()
        (tmp_path / str(dataset_id)).mkdir()

        result = process_dataset_files(
            dataset_id,
            [str(orders_file), str(customers_file)],
            tmp_path,
        )

        assert result["table_count"] == 2
        relationships = result["schema_profile"]["detected_relationships"]
        assert len(relationships) >= 1
        rel = relationships[0]
        assert rel["from_column"] == "customer_id"
        assert rel["to_column"] == "customer_id"
