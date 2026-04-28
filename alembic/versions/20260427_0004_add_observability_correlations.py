"""add observability correlations table

Revision ID: 20260427_0004
Revises: 20260328_0003
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260427_0004"
down_revision: Union[str, Sequence[str], None] = "20260328_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observability_correlations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column(
            "pull_request_id",
            sa.Integer(),
            sa.ForeignKey("pull_requests.id"),
            nullable=True,
        ),
        sa.Column(
            "flaky_test_id",
            sa.Integer(),
            sa.ForeignKey("flaky_test_runs.id"),
            nullable=True,
        ),
        sa.Column("repo_full_name", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("dispatch_backend", sa.String(length=80), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("delivery_id", sa.String(length=255), nullable=True),
        sa.Column("github_check_run_id", sa.BigInteger(), nullable=True),
        sa.Column("github_check_run_name", sa.String(length=255), nullable=True),
        sa.Column("github_check_run_status", sa.String(length=80), nullable=True),
        sa.Column("github_check_run_conclusion", sa.String(length=80), nullable=True),
        sa.Column("github_check_run_url", sa.Text(), nullable=True),
        sa.Column("github_workflow_name", sa.String(length=255), nullable=True),
        sa.Column("github_job_name", sa.String(length=255), nullable=True),
        sa.Column("github_run_url", sa.Text(), nullable=True),
        sa.Column("cloudwatch_log_group", sa.String(length=512), nullable=True),
        sa.Column("cloudwatch_log_stream", sa.String(length=512), nullable=True),
        sa.Column("cloudwatch_log_url", sa.Text(), nullable=True),
        sa.Column(
            "event_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_observability_correlations_cloudwatch_log_stream",
        "observability_correlations",
        ["cloudwatch_log_stream"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_commit_sha",
        "observability_correlations",
        ["commit_sha"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_correlation_id",
        "observability_correlations",
        ["correlation_id"],
        unique=True,
    )
    op.create_index(
        "ix_observability_correlations_delivery_id",
        "observability_correlations",
        ["delivery_id"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_flaky_test_id",
        "observability_correlations",
        ["flaky_test_id"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_github_check_run_id",
        "observability_correlations",
        ["github_check_run_id"],
        unique=False,
    )
    op.create_index("ix_observability_correlations_id", "observability_correlations", ["id"])
    op.create_index(
        "ix_observability_correlations_pull_request_id",
        "observability_correlations",
        ["pull_request_id"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_repo_full_name",
        "observability_correlations",
        ["repo_full_name"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_request_id",
        "observability_correlations",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_resource_id",
        "observability_correlations",
        ["resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_resource_type",
        "observability_correlations",
        ["resource_type"],
        unique=False,
    )
    op.create_index(
        "ix_observability_correlations_task_id",
        "observability_correlations",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_observability_correlations_task_id", table_name="observability_correlations")
    op.drop_index(
        "ix_observability_correlations_resource_type",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_resource_id",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_request_id",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_repo_full_name",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_pull_request_id",
        table_name="observability_correlations",
    )
    op.drop_index("ix_observability_correlations_id", table_name="observability_correlations")
    op.drop_index(
        "ix_observability_correlations_github_check_run_id",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_flaky_test_id",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_delivery_id",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_correlation_id",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_commit_sha",
        table_name="observability_correlations",
    )
    op.drop_index(
        "ix_observability_correlations_cloudwatch_log_stream",
        table_name="observability_correlations",
    )
    op.drop_table("observability_correlations")
