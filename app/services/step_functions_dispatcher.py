import json
from typing import Any

import boto3

from app.core.config import Settings, get_settings
from app.core.log_context import get_serialized_log_context
from app.services.async_dispatch import AsyncDispatchResult


class StepFunctionsDispatcher:
    backend_name = "sqs_step_functions"

    def __init__(self, client: Any | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or boto3.client("stepfunctions", region_name=self.settings.aws_region)

    def dispatch_pull_request_analysis(self, pull_request_id: int) -> AsyncDispatchResult:
        return self._start_execution(
            workflow_name="pull_request_analysis",
            resource_id=pull_request_id,
        )

    def dispatch_flaky_test_triage(self, flaky_test_id: int) -> AsyncDispatchResult:
        return self._start_execution(
            workflow_name="flaky_test_triage",
            resource_id=flaky_test_id,
        )

    def _start_execution(self, *, workflow_name: str, resource_id: int) -> AsyncDispatchResult:
        state_machine_arn = self.settings.step_functions_state_machine_arn.strip()
        if not state_machine_arn:
            raise RuntimeError(
                "STEP_FUNCTIONS_STATE_MACHINE_ARN is required when async_dispatch_backend="
                "sqs_step_functions"
            )

        payload = {
            "workflow_name": workflow_name,
            "resource_id": resource_id,
            "trace_context": get_serialized_log_context(),
        }
        response = self.client.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(payload),
        )
        return AsyncDispatchResult(
            task_id=response.get("executionArn"),
            backend_name=self.backend_name,
        )
