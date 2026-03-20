from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FlakyTestRun(Base):
    __tablename__ = "flaky_test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    test_name: Mapped[str] = mapped_column(String(255), index=True)
    suite_name: Mapped[str] = mapped_column(String(255), index=True)
    branch_name: Mapped[str] = mapped_column(String(255))
    failure_log: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster_key: Mapped[str] = mapped_column(String(255), default="pending")
    suspected_root_cause: Mapped[str] = mapped_column(Text, default="")
    suggested_fix: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
