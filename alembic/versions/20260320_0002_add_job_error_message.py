"""add job error_message columns

Revision ID: 20260320_0002
Revises: 20260319_0001
Create Date: 2026-03-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260320_0002"
down_revision: Union[str, Sequence[str], None] = "20260319_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pull_requests", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("flaky_test_runs", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("flaky_test_runs", "error_message")
    op.drop_column("pull_requests", "error_message")
