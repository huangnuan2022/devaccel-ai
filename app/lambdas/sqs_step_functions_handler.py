from typing import Any

from app.services.sqs_step_functions_consumer import SqsStepFunctionsLambdaConsumer


def handler(event: dict[str, Any], context: Any) -> dict[str, object]:
    del context
    execution_arns = SqsStepFunctionsLambdaConsumer().consume_event(event)
    return {
        "status": "ok",
        "started_execution_count": len(execution_arns),
        "started_execution_arns": execution_arns,
    }
