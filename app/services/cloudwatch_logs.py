from dataclasses import dataclass
from typing import Any

import boto3

from app.core.config import Settings, get_settings
from app.services.exceptions import CloudWatchLogsLookupError


@dataclass
class CloudWatchLogEvent:
    message: str
    timestamp: int | None = None
    ingestion_time: int | None = None
    event_id: str | None = None
    log_stream_name: str | None = None


class CloudWatchLogsService:
    def __init__(self, client: Any | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or boto3.client("logs", region_name=self.settings.aws_region)

    def get_events(
        self,
        *,
        log_group_name: str,
        log_stream_name: str | None = None,
        filter_pattern: str | None = None,
        limit: int = 50,
    ) -> list[CloudWatchLogEvent]:
        normalized_limit = max(1, min(limit, 100))
        try:
            if log_stream_name:
                response = self.client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=log_stream_name,
                    limit=normalized_limit,
                    startFromHead=False,
                )
                return [
                    self._parse_event(event, default_log_stream_name=log_stream_name)
                    for event in response.get("events", [])
                ]

            request: dict[str, object] = {
                "logGroupName": log_group_name,
                "limit": normalized_limit,
            }
            if filter_pattern:
                request["filterPattern"] = filter_pattern
            response = self.client.filter_log_events(**request)
        except Exception as exc:
            raise CloudWatchLogsLookupError(f"CloudWatch log lookup failed: {exc}") from exc

        return [self._parse_event(event) for event in response.get("events", [])]

    @staticmethod
    def _parse_event(
        event: dict[str, Any], default_log_stream_name: str | None = None
    ) -> CloudWatchLogEvent:
        message = event.get("message")
        return CloudWatchLogEvent(
            message=message if isinstance(message, str) else "",
            timestamp=event.get("timestamp") if isinstance(event.get("timestamp"), int) else None,
            ingestion_time=(
                event.get("ingestionTime")
                if isinstance(event.get("ingestionTime"), int)
                else None
            ),
            event_id=event.get("eventId") if isinstance(event.get("eventId"), str) else None,
            log_stream_name=(
                event.get("logStreamName")
                if isinstance(event.get("logStreamName"), str)
                else default_log_stream_name
            ),
        )
