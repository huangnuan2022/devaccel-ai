"""add ci metadata columns to flaky test runs

Revision ID: 20260328_0003
Revises: 20260320_0002
Create Date: 2026-03-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260328_0003"
down_revision: Union[str, Sequence[str], None] = "20260320_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flaky_test_runs", sa.Column("ci_provider", sa.String(length=120), nullable=True))
    op.add_column("flaky_test_runs", sa.Column("workflow_name", sa.String(length=255), nullable=True))
    op.add_column("flaky_test_runs", sa.Column("job_name", sa.String(length=255), nullable=True))
    op.add_column("flaky_test_runs", sa.Column("run_url", sa.Text(), nullable=True))
    op.add_column("flaky_test_runs", sa.Column("commit_sha", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("flaky_test_runs", "commit_sha")
    op.drop_column("flaky_test_runs", "run_url")
    op.drop_column("flaky_test_runs", "job_name")
    op.drop_column("flaky_test_runs", "workflow_name")
    op.drop_column("flaky_test_runs", "ci_provider")
