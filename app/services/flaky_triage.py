import logging
import re

from sqlalchemy.orm import Session

from app.core.log_context import bind_log_context
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
            ci_provider=payload.ci_provider,
            workflow_name=payload.workflow_name,
            job_name=payload.job_name,
            run_url=payload.run_url,
            commit_sha=payload.commit_sha,
            failure_log=payload.failure_log,
            status="queued",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        with bind_log_context(flaky_test_id=run.id):
            logger.info(
                "Created flaky triage job id=%s test_name=%s branch=%s ci_provider=%s workflow_name=%s job_name=%s",
                run.id,
                run.test_name,
                run.branch_name,
                run.ci_provider,
                run.workflow_name,
                run.job_name,
            )
        return run

    def process_triage(self, flaky_test_id: int) -> FlakyTestRun:
        run = self.db.get(FlakyTestRun, flaky_test_id)
        if run is None:
            raise ValueError(f"Flaky test run {flaky_test_id} not found")

        with bind_log_context(flaky_test_id=run.id):
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

            run.cluster_key = self._resolve_cluster_key(
                run.test_name,
                run.suite_name,
                result.cluster_key,
            )
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
        with bind_log_context(flaky_test_id=run.id):
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
        with bind_log_context(flaky_test_id=run.id):
            logger.warning(
                "Marked flaky triage failed id=%s error_message=%s",
                run.id,
                run.error_message,
            )
        return run

    def get_triage(self, flaky_test_id: int) -> FlakyTestRun | None:
        return self.db.get(FlakyTestRun, flaky_test_id)

    def _resolve_cluster_key(self, test_name: str, suite_name: str, cluster_key: str) -> str:
        canonical = self._canonicalize_cluster_key(test_name, cluster_key)
        historical_match = self._find_historical_cluster_match(
            suite_name=suite_name,
            test_name=test_name,
            candidate_cluster_key=canonical,
        )
        if historical_match is not None and historical_match != canonical:
            logger.info(
                "Reused historical flaky cluster key candidate=%s canonical=%s suite_name=%s test_name=%s",
                canonical,
                historical_match,
                suite_name,
                test_name,
            )
            return historical_match
        return canonical

    def _canonicalize_cluster_key(self, test_name: str, cluster_key: str) -> str:
        candidate = cluster_key.strip()
        if candidate.lower().startswith("cluster:"):
            candidate = candidate.split(":", 1)[1]

        normalized = self._slugify_cluster_value(candidate)
        if normalized in {"", "pending", "unknown", "none", "n_a", "na"}:
            normalized = self._slugify_cluster_value(test_name)

        canonical = f"cluster:{normalized}"
        if canonical != cluster_key:
            logger.info(
                "Canonicalized flaky cluster key raw=%s canonical=%s test_name=%s",
                cluster_key,
                canonical,
                test_name,
            )
        return canonical

    @staticmethod
    def _slugify_cluster_value(value: str) -> str:
        normalized = value.lower().replace("::", "_")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized)
        return normalized.strip("_")

    def _find_historical_cluster_match(
        self,
        *,
        suite_name: str,
        test_name: str,
        candidate_cluster_key: str,
    ) -> str | None:
        candidate_tokens = self._cluster_tokens(candidate_cluster_key)
        if not candidate_tokens:
            return None

        exact_test_history = (
            self.db.query(FlakyTestRun)
            .filter(
                FlakyTestRun.suite_name == suite_name,
                FlakyTestRun.test_name == test_name,
                FlakyTestRun.status == "completed",
                FlakyTestRun.cluster_key != "pending",
            )
            .order_by(FlakyTestRun.id.desc())
            .limit(10)
            .all()
        )
        for historical_run in exact_test_history:
            if self._cluster_similarity(candidate_cluster_key, historical_run.cluster_key) >= 0.5:
                return historical_run.cluster_key

        suite_history = (
            self.db.query(FlakyTestRun)
            .filter(
                FlakyTestRun.suite_name == suite_name,
                FlakyTestRun.status == "completed",
                FlakyTestRun.cluster_key != "pending",
            )
            .order_by(FlakyTestRun.id.desc())
            .limit(50)
            .all()
        )

        best_match: str | None = None
        best_score = 0.0
        for historical_run in suite_history:
            score = self._cluster_similarity(candidate_cluster_key, historical_run.cluster_key)
            if score >= 0.6 and score > best_score:
                best_match = historical_run.cluster_key
                best_score = score

        return best_match

    @staticmethod
    def _cluster_tokens(cluster_key: str) -> set[str]:
        normalized = cluster_key.removeprefix("cluster:")
        return {token for token in normalized.split("_") if token}

    @classmethod
    def _cluster_similarity(cls, left: str, right: str) -> float:
        left_tokens = cls._cluster_tokens(left)
        right_tokens = cls._cluster_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = left_tokens & right_tokens
        union = left_tokens | right_tokens
        return len(intersection) / len(union)
