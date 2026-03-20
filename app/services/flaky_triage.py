from sqlalchemy.orm import Session

from app.models.flaky_test import FlakyTestRun
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.services.llm import LLMClient


class FlakyTestService:
    def __init__(self, db: Session, llm_client: LLMClient | None = None) -> None:
        self.db = db
        self.llm_client = llm_client or LLMClient()

    def create_triage_job(self, payload: FlakyTestTriageRequest) -> FlakyTestRun:
        run = FlakyTestRun(
            test_name=payload.test_name,
            suite_name=payload.suite_name,
            branch_name=payload.branch_name,
            failure_log=payload.failure_log,
            status="queued",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def process_triage(self, flaky_test_id: int) -> FlakyTestRun:
        run = self.db.get(FlakyTestRun, flaky_test_id)
        if run is None:
            raise ValueError(f"Flaky test run {flaky_test_id} not found")

        result = self.llm_client.triage_flaky_test(run.test_name, run.failure_log)
        run.cluster_key = result.cluster_key
        run.suspected_root_cause = result.suspected_root_cause
        run.suggested_fix = result.suggested_fix
        run.status = "completed"
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_dispatch_failed(self, flaky_test_id: int) -> FlakyTestRun:
        run = self.db.get(FlakyTestRun, flaky_test_id)
        if run is None:
            raise ValueError(f"Flaky test run {flaky_test_id} not found")

        run.status = "dispatch_failed"
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_triage(self, flaky_test_id: int) -> FlakyTestRun | None:
        return self.db.get(FlakyTestRun, flaky_test_id)
