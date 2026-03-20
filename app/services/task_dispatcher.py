from app.tasks.flaky_triage import triage_flaky_test_task
from app.tasks.pr_analysis import analyze_pull_request_task


class TaskDispatcher:
    def dispatch_pull_request_analysis(self, pull_request_id: int) -> None:
        analyze_pull_request_task.delay(pull_request_id)

    def dispatch_flaky_test_triage(self, flaky_test_id: int) -> None:
        triage_flaky_test_task.delay(flaky_test_id)
