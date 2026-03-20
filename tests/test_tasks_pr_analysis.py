from unittest.mock import MagicMock, patch

from app.tasks.pr_analysis import analyze_pull_request_task


def test_analyze_pull_request_task_calls_service_and_closes_db() -> None:
    db = MagicMock()
    service = MagicMock()

    with (
        patch("app.tasks.pr_analysis.SessionLocal", return_value=db),
        patch("app.tasks.pr_analysis.PullRequestService", return_value=service),
    ):
        analyze_pull_request_task.run(123)

    service.process_analysis.assert_called_once_with(123)
    db.close.assert_called_once_with()
