"""add model_selection to pipeline_runs

Revision ID: 002_add_model_selection
Revises: 001_initial_schema
Create Date: 2025-05-06 00:00:00.000000

Adds a nullable VARCHAR(100) column `model_selection` to the `pipeline_runs`
table to persist the user's LLM model selection for audit purposes.
"""

from alembic import op
import sqlalchemy as sa

revision = "002_add_model_selection"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("model_selection", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "model_selection")
