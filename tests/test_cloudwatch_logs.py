from app.services.cloudwatch_logs import CloudWatchLogsService


def test_cloudwatch_logs_service_reads_events_from_log_stream() -> None:
    class FakeCloudWatchLogsClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def get_log_events(self, **kwargs: object) -> dict[str, list[dict[str, object]]]:
            self.calls.append(kwargs)
            return {
                "events": [
                    {
                        "eventId": "event-1",
                        "timestamp": 1714200000000,
                        "ingestionTime": 1714200000100,
                        "message": "task-123 failed with TimeoutError",
                    }
                ]
            }

    client = FakeCloudWatchLogsClient()
    service = CloudWatchLogsService(client=client)

    events = service.get_events(
        log_group_name="/aws/ecs/devaccel",
        log_stream_name="ecs/api/task-123",
        limit=10,
    )

    assert client.calls == [
        {
            "logGroupName": "/aws/ecs/devaccel",
            "logStreamName": "ecs/api/task-123",
            "limit": 10,
            "startFromHead": False,
        }
    ]
    assert len(events) == 1
    assert events[0].event_id == "event-1"
    assert events[0].log_stream_name == "ecs/api/task-123"
    assert events[0].message == "task-123 failed with TimeoutError"


def test_cloudwatch_logs_service_filters_group_events_without_stream() -> None:
    class FakeCloudWatchLogsClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def filter_log_events(self, **kwargs: object) -> dict[str, list[dict[str, object]]]:
            self.calls.append(kwargs)
            return {
                "events": [
                    {
                        "eventId": "event-2",
                        "logStreamName": "ecs/worker/task-456",
                        "timestamp": 1714200000200,
                        "message": "request_id=req-456 completed",
                    }
                ]
            }

    client = FakeCloudWatchLogsClient()
    service = CloudWatchLogsService(client=client)

    events = service.get_events(
        log_group_name="/aws/ecs/devaccel",
        filter_pattern='"req-456"',
        limit=200,
    )

    assert client.calls == [
        {
            "logGroupName": "/aws/ecs/devaccel",
            "limit": 100,
            "filterPattern": '"req-456"',
        }
    ]
    assert events[0].log_stream_name == "ecs/worker/task-456"
