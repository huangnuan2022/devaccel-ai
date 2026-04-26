from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PullRequestRecord(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    delivery_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    installation_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    pr_number: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(120))
    diff_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    analyses: Mapped[list["PullRequestAnalysis"]] = relationship(back_populates="pull_request")


class PullRequestAnalysis(Base):
    __tablename__ = "pull_request_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    risks: Mapped[str] = mapped_column(Text)
    suggested_tests: Mapped[str] = mapped_column(Text)
    model_provider: Mapped[str] = mapped_column(String(50), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pull_request: Mapped[PullRequestRecord] = relationship(back_populates="analyses")
