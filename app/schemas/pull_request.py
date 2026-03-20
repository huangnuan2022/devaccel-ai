from datetime import datetime

from pydantic import BaseModel, Field


class PullRequestAnalyzeRequest(BaseModel):
    repo_full_name: str = Field(..., examples=["acme/payments"])
    pr_number: int = Field(..., examples=[42])
    title: str = Field(..., examples=["Refactor payment retry flow"])
    author: str = Field(..., examples=["alice"])
    installation_id: int | None = Field(default=None, examples=[12345678])
    diff_text: str = Field(..., description="Unified diff text")


class PullRequestAnalysisResponse(BaseModel):
    id: int
    repo_full_name: str
    pr_number: int
    title: str
    author: str
    status: str
    error_message: str | None = None
    summary: str | None = None
    risks: str | None = None
    suggested_tests: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
