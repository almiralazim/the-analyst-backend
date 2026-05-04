"""initial_schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-01-01 00:00:00.000000

Creates all 7 tables for the The Analyst Backend:
users, datasets, pipeline_runs, agent_executions,
analysis_results, corrections, learnings.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_USERS_ID_FK = ["users.id"]


def upgrade() -> None:
    # --- users (no FK dependencies) ---
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("role", sa.String(50), nullable=True),
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # --- datasets (depends on users) ---
    op.create_table(
        "datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("duckdb_path", sa.String(500), nullable=True),
        sa.Column(
            "schema_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("table_count", sa.Integer(), nullable=True),
        sa.Column("total_rows", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], _USERS_ID_FK, ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_datasets_user_id"), "datasets", ["user_id"], unique=False
    )

    # --- pipeline_runs (depends on users, datasets) ---
    op.create_table(
        "pipeline_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "dataset_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("complexity", sa.String(5), nullable=True),
        sa.Column("execution_plan", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence_grade", sa.String(2), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "context_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], _USERS_ID_FK, ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pipeline_runs_user_id"),
        "pipeline_runs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pipeline_runs_dataset_id"),
        "pipeline_runs",
        ["dataset_id"],
        unique=False,
    )

    # --- agent_executions (depends on pipeline_runs) ---
    op.create_table(
        "agent_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "output_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_executions_pipeline_run_id"),
        "agent_executions",
        ["pipeline_run_id"],
        unique=False,
    )

    # --- analysis_results (depends on pipeline_runs) ---
    op.create_table(
        "analysis_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("result_type", sa.String(50), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("chart_path", sa.String(500), nullable=True),
        sa.Column("ordering", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analysis_results_pipeline_run_id"),
        "analysis_results",
        ["pipeline_run_id"],
        unique=False,
    )

    # --- corrections (depends on users, datasets) ---
    op.create_table(
        "corrections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sql_before", sa.Text(), nullable=True),
        sa.Column("sql_after", sa.Text(), nullable=True),
        sa.Column("prevention_rule", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], _USERS_ID_FK, ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_corrections_user_id"),
        "corrections",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_corrections_dataset_id"),
        "corrections",
        ["dataset_id"],
        unique=False,
    )

    # --- learnings (depends on users) ---
    op.create_table(
        "learnings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=_UUID_DEFAULT,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], _USERS_ID_FK, ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_learnings_user_id"),
        "learnings",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order.
    # Tables with foreign keys to other tables must be dropped first.
    op.drop_index(
        op.f("ix_learnings_user_id"), table_name="learnings"
    )
    op.drop_table("learnings")

    op.drop_index(
        op.f("ix_corrections_dataset_id"), table_name="corrections"
    )
    op.drop_index(
        op.f("ix_corrections_user_id"), table_name="corrections"
    )
    op.drop_table("corrections")

    op.drop_index(
        op.f("ix_analysis_results_pipeline_run_id"),
        table_name="analysis_results",
    )
    op.drop_table("analysis_results")

    op.drop_index(
        op.f("ix_agent_executions_pipeline_run_id"),
        table_name="agent_executions",
    )
    op.drop_table("agent_executions")

    op.drop_index(
        op.f("ix_pipeline_runs_dataset_id"), table_name="pipeline_runs"
    )
    op.drop_index(
        op.f("ix_pipeline_runs_user_id"), table_name="pipeline_runs"
    )
    op.drop_table("pipeline_runs")

    op.drop_index(
        op.f("ix_datasets_user_id"), table_name="datasets"
    )
    op.drop_table("datasets")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
