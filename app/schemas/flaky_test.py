from datetime import datetime

from pydantic import BaseModel, Field


class FlakyTestTriageRequest(BaseModel):
    test_name: str = Field(..., examples=["test_retry_payment_timeout"])
    suite_name: str = Field(..., examples=["payments.integration"])
    branch_name: str = Field(..., examples=["main"])
    ci_provider: str | None = Field(default=None, examples=["github_actions"])
    repo_full_name: str | None = Field(default=None, examples=["acme/payments"])
    workflow_name: str | None = Field(default=None, examples=["CI"])
    job_name: str | None = Field(default=None, examples=["pytest"])
    run_url: str | None = Field(
        default=None, examples=["https://github.com/acme/payments/actions/runs/123"]
    )
    commit_sha: str | None = Field(default=None, examples=["abc123def456"])
    github_check_run_id: int | None = Field(default=None, examples=[123456789])
    github_check_run_name: str | None = Field(default=None, examples=["pytest"])
    github_check_run_status: str | None = Field(default=None, examples=["completed"])
    github_check_run_conclusion: str | None = Field(default=None, examples=["failure"])
    github_check_run_url: str | None = Field(
        default=None, examples=["https://github.com/acme/payments/runs/123456789"]
    )
    cloudwatch_log_group: str | None = Field(default=None, examples=["/aws/ecs/devaccel"])
    cloudwatch_log_stream: str | None = Field(default=None, examples=["ecs/api/task-123"])
    cloudwatch_log_url: str | None = None
    failure_log: str = Field(..., description="Raw CI failure log")


class FlakyTestTriageResponse(BaseModel):
    id: int
    test_name: str
    suite_name: str
    branch_name: str
    ci_provider: str | None = None
    workflow_name: str | None = None
    job_name: str | None = None
    run_url: str | None = None
    commit_sha: str | None = None
    status: str
    error_message: str | None = None
    cluster_key: str
    suspected_root_cause: str
    suggested_fix: str
    created_at: datetime

    model_config = {"from_attributes": True}
