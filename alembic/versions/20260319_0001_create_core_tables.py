"""create core tables

Revision ID: 20260319_0001
Revises: None
Create Date: 2026-03-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260319_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "flaky_test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_name", sa.String(length=255), nullable=False),
        sa.Column("suite_name", sa.String(length=255), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("failure_log", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "cluster_key",
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "suspected_root_cause",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "suggested_fix",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Note: update-time refresh currently lives in the ORM via onupdate=func.now().
        # If we later need DB-enforced updated_at semantics, add a dedicated migration.
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_flaky_test_runs_id", "flaky_test_runs", ["id"], unique=False)
    op.create_index("ix_flaky_test_runs_suite_name", "flaky_test_runs", ["suite_name"], unique=False)
    op.create_index("ix_flaky_test_runs_test_name", "flaky_test_runs", ["test_name"], unique=False)

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.String(length=255), nullable=True),
        sa.Column("installation_id", sa.Integer(), nullable=True),
        sa.Column("repo_full_name", sa.String(length=255), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Note: update-time refresh currently lives in the ORM via onupdate=func.now().
        # If we later need DB-enforced updated_at semantics, add a dedicated migration.
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pull_requests_delivery_id", "pull_requests", ["delivery_id"], unique=True)
    op.create_index("ix_pull_requests_id", "pull_requests", ["id"], unique=False)
    op.create_index("ix_pull_requests_installation_id", "pull_requests", ["installation_id"], unique=False)
    op.create_index("ix_pull_requests_pr_number", "pull_requests", ["pr_number"], unique=False)
    op.create_index("ix_pull_requests_repo_full_name", "pull_requests", ["repo_full_name"], unique=False)

    op.create_table(
        "pull_request_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risks", sa.Text(), nullable=False),
        sa.Column("suggested_tests", sa.Text(), nullable=False),
        sa.Column(
            "model_provider",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'mock'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pull_request_analyses_id", "pull_request_analyses", ["id"], unique=False)
    op.create_index(
        "ix_pull_request_analyses_pull_request_id",
        "pull_request_analyses",
        ["pull_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pull_request_analyses_pull_request_id", table_name="pull_request_analyses")
    op.drop_index("ix_pull_request_analyses_id", table_name="pull_request_analyses")
    op.drop_table("pull_request_analyses")

    op.drop_index("ix_pull_requests_repo_full_name", table_name="pull_requests")
    op.drop_index("ix_pull_requests_pr_number", table_name="pull_requests")
    op.drop_index("ix_pull_requests_installation_id", table_name="pull_requests")
    op.drop_index("ix_pull_requests_id", table_name="pull_requests")
    op.drop_index("ix_pull_requests_delivery_id", table_name="pull_requests")
    op.drop_table("pull_requests")

    op.drop_index("ix_flaky_test_runs_test_name", table_name="flaky_test_runs")
    op.drop_index("ix_flaky_test_runs_suite_name", table_name="flaky_test_runs")
    op.drop_index("ix_flaky_test_runs_id", table_name="flaky_test_runs")
    op.drop_table("flaky_test_runs")
