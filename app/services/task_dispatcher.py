from app.services.async_dispatch import AsyncDispatchResult
from app.core.log_context import get_serialized_log_context
from app.tasks.flaky_triage import triage_flaky_test_task
from app.tasks.pr_analysis import analyze_pull_request_task


class TaskDispatcher:
    backend_name = "celery"

    def dispatch_pull_request_analysis(self, pull_request_id: int) -> AsyncDispatchResult:
        task = analyze_pull_request_task.apply_async(
            args=[pull_request_id],
            headers=get_serialized_log_context(),
        )
        return AsyncDispatchResult(task_id=task.id, backend_name=self.backend_name)

    def dispatch_flaky_test_triage(self, flaky_test_id: int) -> AsyncDispatchResult:
        task = triage_flaky_test_task.apply_async(
            args=[flaky_test_id],
            headers=get_serialized_log_context(),
        )
        return AsyncDispatchResult(task_id=task.id, backend_name=self.backend_name)
