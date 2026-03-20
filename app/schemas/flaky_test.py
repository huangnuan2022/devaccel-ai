from datetime import datetime

from pydantic import BaseModel, Field


class FlakyTestTriageRequest(BaseModel):
    test_name: str = Field(..., examples=["test_retry_payment_timeout"])
    suite_name: str = Field(..., examples=["payments.integration"])
    branch_name: str = Field(..., examples=["main"])
    failure_log: str = Field(..., description="Raw CI failure log")


class FlakyTestTriageResponse(BaseModel):
    id: int
    test_name: str
    suite_name: str
    branch_name: str
    status: str
    error_message: str | None = None
    cluster_key: str
    suspected_root_cause: str
    suggested_fix: str
    created_at: datetime

    model_config = {"from_attributes": True}
