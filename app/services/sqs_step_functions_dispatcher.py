from typing import Any

import boto3

from app.core.config import Settings, get_settings
from app.schemas.async_dispatch import SqsStepFunctionsDispatchMessage
from app.services.async_dispatch import AsyncDispatchResult
from app.services.step_functions_dispatcher import (
    build_step_functions_execution_input,
    resolve_state_machine_arn,
)


class SqsStepFunctionsDispatcher:
    backend_name = "sqs_step_functions"

    def __init__(self, client: Any | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or boto3.client("sqs", region_name=self.settings.aws_region)

    def dispatch_pull_request_analysis(self, pull_request_id: int) -> AsyncDispatchResult:
        return self._send_start_execution_message(
            workflow_name="pull_request_analysis",
            resource_type="pull_request",
            resource_id=pull_request_id,
        )

    def dispatch_flaky_test_triage(self, flaky_test_id: int) -> AsyncDispatchResult:
        return self._send_start_execution_message(
            workflow_name="flaky_test_triage",
            resource_type="flaky_test_run",
            resource_id=flaky_test_id,
        )

    def _send_start_execution_message(
        self,
        *,
        workflow_name: str,
        resource_type: str,
        resource_id: int,
    ) -> AsyncDispatchResult:
        queue_url = self.settings.sqs_queue_url.strip()
        if not queue_url:
            raise RuntimeError(
                "SQS_QUEUE_URL is required when async_dispatch_backend=sqs_step_functions"
            )

        state_machine_arn = resolve_state_machine_arn(self.settings, workflow_name)
        if not state_machine_arn:
            raise RuntimeError(
                f"A Step Functions state machine ARN is required for workflow '{workflow_name}' "
                "when async_dispatch_backend=sqs_step_functions"
            )

        message = SqsStepFunctionsDispatchMessage(
            state_machine_arn=state_machine_arn,
            execution_input=build_step_functions_execution_input(
                workflow_name=workflow_name,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
        )
        response = self.client.send_message(
            QueueUrl=queue_url,
            MessageBody=message.model_dump_json(),
        )
        return AsyncDispatchResult(
            task_id=response.get("MessageId"),
            backend_name=self.backend_name,
        )
