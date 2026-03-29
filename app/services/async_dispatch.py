from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AsyncDispatchResult:
    task_id: str | None
    backend_name: str


class AsyncWorkflowDispatcher(Protocol):
    backend_name: str

    def dispatch_pull_request_analysis(self, pull_request_id: int) -> AsyncDispatchResult: ...

    def dispatch_flaky_test_triage(self, flaky_test_id: int) -> AsyncDispatchResult: ...
