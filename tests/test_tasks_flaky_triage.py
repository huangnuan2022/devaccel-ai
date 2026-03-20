from unittest.mock import MagicMock, patch

from app.tasks.flaky_triage import triage_flaky_test_task


def test_triage_flaky_test_task_calls_service_and_closes_db() -> None:
    db = MagicMock()
    service = MagicMock()

    with (
        patch("app.tasks.flaky_triage.SessionLocal", return_value=db),
        patch("app.tasks.flaky_triage.FlakyTestService", return_value=service),
    ):
        triage_flaky_test_task.run(456)

    service.process_triage.assert_called_once_with(456)
    db.close.assert_called_once_with()
