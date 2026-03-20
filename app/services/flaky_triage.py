import logging

from sqlalchemy.orm import Session

from app.models.flaky_test import FlakyTestRun
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.services.exceptions import (
    LLMProviderConfigurationError,
    LLMProviderInvocationError,
)
from app.services.llm import LLMClient


logger = logging.getLogger(__name__)


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
        logger.info(
            "Created flaky triage job id=%s test_name=%s branch=%s",
            run.id,
            run.test_name,
            run.branch_name,
        )
        return run

    def process_triage(self, flaky_test_id: int) -> FlakyTestRun:
        run = self.db.get(FlakyTestRun, flaky_test_id)
        if run is None:
            raise ValueError(f"Flaky test run {flaky_test_id} not found")

        logger.info(
            "Starting flaky triage processing id=%s test_name=%s status=%s",
            run.id,
            run.test_name,
            run.status,
        )

        try:
            result = self.llm_client.triage_flaky_test(run.test_name, run.failure_log)
        except (LLMProviderConfigurationError, LLMProviderInvocationError) as exc:
            logger.warning(
                "Flaky triage failed id=%s test_name=%s error=%s",
                run.id,
                run.test_name,
                exc,
            )
            self.mark_processing_failed(run.id, str(exc))
            raise

        run.cluster_key = result.cluster_key
        run.suspected_root_cause = result.suspected_root_cause
        run.suggested_fix = result.suggested_fix
        run.status = "completed"
        run.error_message = None
        self.db.commit()
        self.db.refresh(run)
        logger.info(
            "Completed flaky triage id=%s provider=%s cluster_key=%s",
            run.id,
            self.llm_client.provider_name,
            run.cluster_key,
        )
        return run

    def mark_dispatch_failed(self, flaky_test_id: int, error_message: str | None = None) -> FlakyTestRun:
        run = self.db.get(FlakyTestRun, flaky_test_id)
        if run is None:
            raise ValueError(f"Flaky test run {flaky_test_id} not found")

        run.status = "dispatch_failed"
        run.error_message = error_message
        self.db.commit()
        self.db.refresh(run)
        logger.warning(
            "Marked flaky triage dispatch_failed id=%s error_message=%s",
            run.id,
            run.error_message,
        )
        return run

    def mark_processing_failed(self, flaky_test_id: int, error_message: str) -> FlakyTestRun:
        run = self.db.get(FlakyTestRun, flaky_test_id)
        if run is None:
            raise ValueError(f"Flaky test run {flaky_test_id} not found")

        run.status = "failed"
        run.error_message = error_message
        self.db.commit()
        self.db.refresh(run)
        logger.warning(
            "Marked flaky triage failed id=%s error_message=%s",
            run.id,
            run.error_message,
        )
        return run

    def get_triage(self, flaky_test_id: int) -> FlakyTestRun | None:
        return self.db.get(FlakyTestRun, flaky_test_id)
