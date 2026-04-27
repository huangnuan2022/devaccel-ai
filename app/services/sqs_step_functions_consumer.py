import logging
from typing import Any

import boto3
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.log_context import bind_log_context, clear_log_context
from app.schemas.async_dispatch import (
    SQSEventPayload,
    SQSMessageRecord,
    SqsStepFunctionsDispatchMessage,
)

logger = logging.getLogger(__name__)


class SqsStepFunctionsLambdaConsumer:
    def __init__(self, client: Any | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or boto3.client("stepfunctions", region_name=self.settings.aws_region)

    def consume_event(self, event: dict[str, Any] | SQSEventPayload) -> list[str]:
        payload = (
            event
            if isinstance(event, SQSEventPayload)
            else SQSEventPayload.model_validate(event)
        )
        execution_arns: list[str] = []
        for record in payload.records:
            execution_arns.append(self.consume_record(record))
        return execution_arns

    def consume_record(self, record: SQSMessageRecord) -> str:
        try:
            message = SqsStepFunctionsDispatchMessage.model_validate_json(record.body)
        except ValidationError as exc:
            record_label = record.message_id or "-"
            raise ValueError(
                f"Invalid SQS Step Functions dispatch message for record {record_label}"
            ) from exc

        trace_context = message.execution_input.trace_context
        clear_log_context()
        try:
            with bind_log_context(**trace_context):
                logger.info(
                    "Starting Step Functions execution from SQS message "
                    "message_id=%s workflow_name=%s resource_type=%s resource_id=%s",
                    record.message_id or "-",
                    message.execution_input.workflow_name,
                    message.execution_input.resource_type,
                    message.execution_input.resource_id,
                )
                response = self.client.start_execution(
                    stateMachineArn=message.state_machine_arn,
                    input=message.execution_input.model_dump_json(),
                )
                execution_arn = response.get("executionArn")
                if not isinstance(execution_arn, str) or not execution_arn:
                    raise RuntimeError(
                        "Step Functions start_execution response did not contain executionArn"
                    )
                logger.info(
                    "Started Step Functions execution from SQS message "
                    "message_id=%s execution_arn=%s",
                    record.message_id or "-",
                    execution_arn,
                )
                return execution_arn
        finally:
            clear_log_context()
