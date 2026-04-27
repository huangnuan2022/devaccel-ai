from typing import Literal

from pydantic import BaseModel, Field


class StepFunctionsExecutionInput(BaseModel):
    workflow_name: str = Field(..., examples=["pull_request_analysis"])
    resource_type: str = Field(..., examples=["pull_request"])
    resource_id: int = Field(..., examples=[42])
    trace_context: dict[str, str] = Field(default_factory=dict)


class SqsStepFunctionsDispatchMessage(BaseModel):
    message_type: Literal["start_step_function_execution"] = "start_step_function_execution"
    state_machine_arn: str
    execution_input: StepFunctionsExecutionInput


class SQSMessageRecord(BaseModel):
    message_id: str | None = Field(default=None, alias="messageId")
    body: str


class SQSEventPayload(BaseModel):
    records: list[SQSMessageRecord] = Field(default_factory=list, alias="Records")
