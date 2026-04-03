from pydantic import BaseModel, Field


class StepFunctionsExecutionInput(BaseModel):
    workflow_name: str = Field(..., examples=["pull_request_analysis"])
    resource_type: str = Field(..., examples=["pull_request"])
    resource_id: int = Field(..., examples=[42])
    trace_context: dict[str, str] = Field(default_factory=dict)
