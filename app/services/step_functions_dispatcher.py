from typing import Any

import boto3

from app.core.config import Settings, get_settings
from app.core.log_context import get_serialized_log_context
from app.schemas.async_dispatch import StepFunctionsExecutionInput
from app.services.async_dispatch import AsyncDispatchResult


class StepFunctionsDispatcher:
    backend_name = "sqs_step_functions"

    def __init__(self, client: Any | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or boto3.client("stepfunctions", region_name=self.settings.aws_region)

    def dispatch_pull_request_analysis(self, pull_request_id: int) -> AsyncDispatchResult:
        return self._start_execution(
            workflow_name="pull_request_analysis",
            resource_type="pull_request",
            resource_id=pull_request_id,
        )

    def dispatch_flaky_test_triage(self, flaky_test_id: int) -> AsyncDispatchResult:
        return self._start_execution(
            workflow_name="flaky_test_triage",
            resource_type="flaky_test_run",
            resource_id=flaky_test_id,
        )

    def _start_execution(
        self,
        *,
        workflow_name: str,
        resource_type: str,
        resource_id: int,
    ) -> AsyncDispatchResult:
        state_machine_arn = self._resolve_state_machine_arn(workflow_name)
        if not state_machine_arn:
            raise RuntimeError(
                f"A Step Functions state machine ARN is required for workflow '{workflow_name}' "
                "when async_dispatch_backend=sqs_step_functions"
            )

        payload = StepFunctionsExecutionInput(
            workflow_name=workflow_name,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_context=get_serialized_log_context(),
        )
        response = self.client.start_execution(
            stateMachineArn=state_machine_arn,
            input=payload.model_dump_json(),
        )
        return AsyncDispatchResult(
            task_id=response.get("executionArn"),
            backend_name=self.backend_name,
        )

    def _resolve_state_machine_arn(self, workflow_name: str) -> str:
        if workflow_name == "pull_request_analysis":
            return (
                self.settings.step_functions_pr_analysis_state_machine_arn.strip()
                or self.settings.step_functions_state_machine_arn.strip()
            )
        if workflow_name == "flaky_test_triage":
            return (
                self.settings.step_functions_flaky_triage_state_machine_arn.strip()
                or self.settings.step_functions_state_machine_arn.strip()
            )
        return self.settings.step_functions_state_machine_arn.strip()
