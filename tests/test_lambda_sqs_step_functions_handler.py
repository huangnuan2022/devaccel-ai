import json
from unittest.mock import Mock, patch

from app.lambdas.sqs_step_functions_handler import handler
from app.schemas.async_dispatch import SQSEventPayload, SQSMessageRecord
from app.services.sqs_step_functions_consumer import SqsStepFunctionsLambdaConsumer


def test_sqs_step_functions_lambda_consumer_starts_execution_for_each_record() -> None:
    captured_calls: list[dict[str, object]] = []

    class FakeStepFunctionsClient:
        def start_execution(self, **kwargs: object) -> dict[str, str]:
            captured_calls.append(kwargs)
            resource_id = json.loads(str(kwargs["input"]))["resource_id"]
            return {"executionArn": f"arn:aws:states:execution:devaccel:{resource_id}"}

    consumer = SqsStepFunctionsLambdaConsumer(client=FakeStepFunctionsClient())
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(
                    {
                        "message_type": "start_step_function_execution",
                        "state_machine_arn": "arn:aws:states:stateMachine:pr-analysis",
                        "execution_input": {
                            "workflow_name": "pull_request_analysis",
                            "resource_type": "pull_request",
                            "resource_id": 42,
                            "trace_context": {
                                "request_id": "req-123",
                                "delivery_id": "delivery-123",
                            },
                        },
                    }
                ),
            },
            {
                "messageId": "msg-2",
                "body": json.dumps(
                    {
                        "message_type": "start_step_function_execution",
                        "state_machine_arn": "arn:aws:states:stateMachine:flaky-triage",
                        "execution_input": {
                            "workflow_name": "flaky_test_triage",
                            "resource_type": "flaky_test_run",
                            "resource_id": 7,
                            "trace_context": {"request_id": "req-456"},
                        },
                    }
                ),
            },
        ]
    }

    execution_arns = consumer.consume_event(event)

    assert execution_arns == [
        "arn:aws:states:execution:devaccel:42",
        "arn:aws:states:execution:devaccel:7",
    ]
    assert len(captured_calls) == 2
    assert captured_calls[0]["stateMachineArn"] == "arn:aws:states:stateMachine:pr-analysis"
    assert json.loads(str(captured_calls[0]["input"]))["workflow_name"] == "pull_request_analysis"
    assert captured_calls[1]["stateMachineArn"] == "arn:aws:states:stateMachine:flaky-triage"
    assert json.loads(str(captured_calls[1]["input"]))["workflow_name"] == "flaky_test_triage"


def test_sqs_step_functions_lambda_consumer_accepts_prevalidated_payload() -> None:
    client = Mock()
    client.start_execution.return_value = {
        "executionArn": "arn:aws:states:execution:devaccel:validated"
    }
    consumer = SqsStepFunctionsLambdaConsumer(client=client)
    payload = SQSEventPayload(
        Records=[
            SQSMessageRecord(
                messageId="msg-validated",
                body=json.dumps(
                    {
                        "message_type": "start_step_function_execution",
                        "state_machine_arn": "arn:aws:states:stateMachine:validated",
                        "execution_input": {
                            "workflow_name": "pull_request_analysis",
                            "resource_type": "pull_request",
                            "resource_id": 99,
                            "trace_context": {},
                        },
                    }
                ),
            )
        ]
    )

    execution_arns = consumer.consume_event(payload)

    assert execution_arns == ["arn:aws:states:execution:devaccel:validated"]
    client.start_execution.assert_called_once()


def test_sqs_step_functions_lambda_consumer_rejects_invalid_record_body() -> None:
    consumer = SqsStepFunctionsLambdaConsumer(client=Mock())

    try:
        consumer.consume_event(
            {
                "Records": [
                    {
                        "messageId": "msg-invalid",
                        "body": json.dumps({"message_type": "wrong"}),
                    }
                ]
            }
        )
    except ValueError as exc:
        assert "msg-invalid" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid SQS Step Functions message body")


def test_sqs_step_functions_lambda_handler_returns_execution_summary() -> None:
    fake_consumer = Mock()
    fake_consumer.consume_event.return_value = [
        "arn:aws:states:execution:devaccel:42",
        "arn:aws:states:execution:devaccel:7",
    ]

    with patch(
        "app.lambdas.sqs_step_functions_handler.SqsStepFunctionsLambdaConsumer",
        return_value=fake_consumer,
    ):
        result = handler({"Records": []}, context=None)

    assert result == {
        "status": "ok",
        "started_execution_count": 2,
        "started_execution_arns": [
            "arn:aws:states:execution:devaccel:42",
            "arn:aws:states:execution:devaccel:7",
        ],
    }
    fake_consumer.consume_event.assert_called_once_with({"Records": []})
