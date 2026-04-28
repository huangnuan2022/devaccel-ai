from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ObservabilityCorrelation(Base):
    __tablename__ = "observability_correlations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    pull_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_requests.id"), index=True, nullable=True
    )
    flaky_test_id: Mapped[int | None] = mapped_column(
        ForeignKey("flaky_test_runs.id"), index=True, nullable=True
    )
    repo_full_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    dispatch_backend: Mapped[str | None] = mapped_column(String(80), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    delivery_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    github_check_run_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    github_check_run_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_check_run_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    github_check_run_conclusion: Mapped[str | None] = mapped_column(String(80), nullable=True)
    github_check_run_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_workflow_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_job_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_run_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloudwatch_log_group: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cloudwatch_log_stream: Mapped[str | None] = mapped_column(
        String(512), index=True, nullable=True
    )
    cloudwatch_log_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
