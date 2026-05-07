"""initial schema — series, pipelines, pipeline_stages, artifacts, approvals.

Revision ID: 001
Revises:
Create Date: 2026-05-07 16:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """5 도메인 테이블 + 인덱스 생성."""

    op.create_table(
        "series",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("outline", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("series_id", sa.Integer, sa.ForeignKey("series.id"), nullable=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="1"),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("current_stage", sa.String(32), nullable=False, server_default="topic"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uk_pipeline_idem"),
    )
    op.create_index("ix_pipelines_status", "pipelines", ["status"])
    op.create_index("ix_pipelines_series_id", "pipelines", ["series_id"])

    op.create_table(
        "pipeline_stages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pipeline_id", sa.Integer, sa.ForeignKey("pipelines.id"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.create_index("ix_pipeline_stages_pipeline_id", "pipeline_stages", ["pipeline_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pipeline_id", sa.Integer, sa.ForeignKey("pipelines.id"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("mime", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_artifacts_pipeline_id", "artifacts", ["pipeline_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pipeline_id", sa.Integer, sa.ForeignKey("pipelines.id"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("approver", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """역순 drop."""
    op.drop_index("ix_artifacts_pipeline_id", table_name="artifacts")
    op.drop_table("approvals")
    op.drop_table("artifacts")
    op.drop_index("ix_pipeline_stages_pipeline_id", table_name="pipeline_stages")
    op.drop_table("pipeline_stages")
    op.drop_index("ix_pipelines_series_id", table_name="pipelines")
    op.drop_index("ix_pipelines_status", table_name="pipelines")
    op.drop_table("pipelines")
    op.drop_table("series")
