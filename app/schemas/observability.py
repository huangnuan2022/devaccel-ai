from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ObservableResourceType = Literal["pull_request", "flaky_test_run"]


class GitHubCheckRunObservationRequest(BaseModel):
    resource_type: ObservableResourceType | None = None
    resource_id: int | None = None
    pull_request_id: int | None = None
    flaky_test_id: int | None = None
    repo_full_name: str | None = Field(default=None, examples=["acme/payments"])
    commit_sha: str | None = Field(default=None, examples=["abc123def456"])
    github_check_run_id: int | None = Field(default=None, examples=[123456789])
    github_check_run_name: str | None = Field(default=None, examples=["pytest"])
    github_check_run_status: str | None = Field(default=None, examples=["completed"])
    github_check_run_conclusion: str | None = Field(default=None, examples=["failure"])
    github_check_run_url: str | None = Field(
        default=None,
        examples=["https://github.com/acme/payments/runs/123456789"],
    )
    github_workflow_name: str | None = Field(default=None, examples=["CI"])
    github_job_name: str | None = Field(default=None, examples=["pytest"])
    github_run_url: str | None = Field(
        default=None,
        examples=["https://github.com/acme/payments/actions/runs/123"],
    )
    cloudwatch_log_group: str | None = Field(default=None, examples=["/aws/ecs/devaccel"])
    cloudwatch_log_stream: str | None = Field(default=None, examples=["ecs/api/task-123"])
    cloudwatch_log_url: str | None = None
    request_id: str | None = None
    delivery_id: str | None = None
    task_id: str | None = None
    event_metadata: dict[str, str] = Field(default_factory=dict)


class ObservabilityCorrelationResponse(BaseModel):
    id: int
    correlation_id: str
    resource_type: str | None = None
    resource_id: int | None = None
    pull_request_id: int | None = None
    flaky_test_id: int | None = None
    repo_full_name: str | None = None
    commit_sha: str | None = None
    dispatch_backend: str | None = None
    task_id: str | None = None
    request_id: str | None = None
    delivery_id: str | None = None
    github_check_run_id: int | None = None
    github_check_run_name: str | None = None
    github_check_run_status: str | None = None
    github_check_run_conclusion: str | None = None
    github_check_run_url: str | None = None
    github_workflow_name: str | None = None
    github_job_name: str | None = None
    github_run_url: str | None = None
    cloudwatch_log_group: str | None = None
    cloudwatch_log_stream: str | None = None
    cloudwatch_log_url: str | None = None
    event_metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
