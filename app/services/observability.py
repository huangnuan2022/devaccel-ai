import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.log_context import bind_log_context, get_serialized_log_context
from app.models.flaky_test import FlakyTestRun
from app.models.observability import ObservabilityCorrelation
from app.models.pull_request import PullRequestRecord
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.schemas.observability import (
    CloudWatchLogEventResponse,
    GitHubCheckRunObservationRequest,
    ObservabilityCloudWatchEventsResponse,
)
from app.services.cloudwatch_logs import CloudWatchLogsService
from app.services.exceptions import CloudWatchLogsLookupError

logger = logging.getLogger(__name__)


class ObservabilityService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def record_flaky_triage_ingest(
        self, run: FlakyTestRun, payload: FlakyTestTriageRequest
    ) -> ObservabilityCorrelation:
        observation = GitHubCheckRunObservationRequest(
            resource_type="flaky_test_run",
            resource_id=run.id,
            flaky_test_id=run.id,
            repo_full_name=self._resolve_flaky_repo_full_name(payload),
            commit_sha=payload.commit_sha,
            github_check_run_id=payload.github_check_run_id,
            github_check_run_name=payload.github_check_run_name or payload.job_name,
            github_check_run_status=payload.github_check_run_status,
            github_check_run_conclusion=payload.github_check_run_conclusion,
            github_check_run_url=payload.github_check_run_url,
            github_workflow_name=payload.workflow_name,
            github_job_name=payload.job_name,
            github_run_url=payload.run_url,
            cloudwatch_log_group=payload.cloudwatch_log_group,
            cloudwatch_log_stream=payload.cloudwatch_log_stream,
            cloudwatch_log_url=payload.cloudwatch_log_url,
        )
        return self.record_github_check_run(observation)

    def record_pull_request_ingest(self, record: PullRequestRecord) -> ObservabilityCorrelation:
        observation = GitHubCheckRunObservationRequest(
            resource_type="pull_request",
            resource_id=record.id,
            pull_request_id=record.id,
            repo_full_name=record.repo_full_name,
            delivery_id=record.delivery_id,
        )
        return self.record_github_check_run(observation)

    def record_dispatch(
        self,
        *,
        resource_type: str,
        resource_id: int,
        task_id: str | None,
        dispatch_backend: str,
    ) -> ObservabilityCorrelation:
        correlation = self._find_by_resource(resource_type, resource_id)
        if correlation is None:
            correlation = ObservabilityCorrelation(
                correlation_id=f"{resource_type}:{resource_id}",
                resource_type=resource_type,
                resource_id=resource_id,
            )
            self._apply_resource_pointer(correlation, resource_type, resource_id)
            self.db.add(correlation)

        correlation.task_id = task_id
        correlation.dispatch_backend = dispatch_backend
        if self.settings.cloudwatch_log_group and not correlation.cloudwatch_log_group:
            correlation.cloudwatch_log_group = self.settings.cloudwatch_log_group

        self.db.commit()
        self.db.refresh(correlation)
        with bind_log_context(
            correlation_id=correlation.correlation_id,
            task_id=task_id,
            cloudwatch_log_stream=correlation.cloudwatch_log_stream,
        ):
            logger.info(
                "Recorded dispatch correlation resource_type=%s resource_id=%s "
                "backend=%s task_id=%s",
                resource_type,
                resource_id,
                dispatch_backend,
                task_id or "-",
            )
        return correlation

    def record_github_check_run(
        self, payload: GitHubCheckRunObservationRequest
    ) -> ObservabilityCorrelation:
        correlation = self._find_existing(payload)
        if correlation is None:
            correlation = ObservabilityCorrelation(
                correlation_id=self._build_correlation_id(payload),
            )
            self.db.add(correlation)

        self._apply_observation(correlation, payload)
        self.db.commit()
        self.db.refresh(correlation)
        with bind_log_context(
            correlation_id=correlation.correlation_id,
            github_check_run_id=correlation.github_check_run_id,
            cloudwatch_log_stream=correlation.cloudwatch_log_stream,
        ):
            logger.info(
                "Recorded GitHub check run correlation correlation_id=%s "
                "resource_type=%s resource_id=%s check_run_id=%s",
                correlation.correlation_id,
                correlation.resource_type or "-",
                correlation.resource_id or "-",
                correlation.github_check_run_id or "-",
            )
        return correlation

    def get_by_correlation_id(self, correlation_id: str) -> ObservabilityCorrelation | None:
        return (
            self.db.query(ObservabilityCorrelation)
            .filter(ObservabilityCorrelation.correlation_id == correlation_id)
            .first()
        )

    def list_for_resource(
        self, resource_type: str, resource_id: int
    ) -> list[ObservabilityCorrelation]:
        return (
            self.db.query(ObservabilityCorrelation)
            .filter(
                ObservabilityCorrelation.resource_type == resource_type,
                ObservabilityCorrelation.resource_id == resource_id,
            )
            .order_by(ObservabilityCorrelation.id.desc())
            .all()
        )

    def get_cloudwatch_events(
        self,
        *,
        correlation_id: str,
        cloudwatch_logs_service: CloudWatchLogsService,
        limit: int = 50,
    ) -> ObservabilityCloudWatchEventsResponse | None:
        correlation = self.get_by_correlation_id(correlation_id)
        if correlation is None:
            return None

        log_group_name = (
            correlation.cloudwatch_log_group or self.settings.cloudwatch_log_group
        ).strip()
        if not log_group_name:
            raise CloudWatchLogsLookupError(
                f"Correlation {correlation_id} does not include a CloudWatch log group"
            )

        log_stream_name = (
            correlation.cloudwatch_log_stream.strip()
            if correlation.cloudwatch_log_stream
            else None
        )
        filter_pattern = self._build_cloudwatch_filter_pattern(correlation)
        with bind_log_context(
            correlation_id=correlation.correlation_id,
            task_id=correlation.task_id,
            github_check_run_id=correlation.github_check_run_id,
            cloudwatch_log_stream=log_stream_name,
        ):
            logger.info(
                "Fetching CloudWatch events correlation_id=%s log_group=%s "
                "log_stream=%s filter_pattern=%s limit=%s",
                correlation.correlation_id,
                log_group_name,
                log_stream_name or "-",
                filter_pattern or "-",
                limit,
            )
            events = cloudwatch_logs_service.get_events(
                log_group_name=log_group_name,
                log_stream_name=log_stream_name,
                filter_pattern=filter_pattern,
                limit=limit,
            )

        return ObservabilityCloudWatchEventsResponse(
            correlation_id=correlation.correlation_id,
            log_group_name=log_group_name,
            log_stream_name=log_stream_name,
            filter_pattern=filter_pattern,
            events=[
                CloudWatchLogEventResponse(
                    message=event.message,
                    timestamp=event.timestamp,
                    ingestion_time=event.ingestion_time,
                    event_id=event.event_id,
                    log_stream_name=event.log_stream_name,
                )
                for event in events
            ],
        )

    def _find_existing(
        self, payload: GitHubCheckRunObservationRequest
    ) -> ObservabilityCorrelation | None:
        if payload.resource_type and payload.resource_id is not None:
            match = self._find_by_resource(payload.resource_type, payload.resource_id)
            if match is not None:
                return match
        if payload.github_check_run_id is not None:
            return (
                self.db.query(ObservabilityCorrelation)
                .filter(
                    ObservabilityCorrelation.github_check_run_id
                    == payload.github_check_run_id
                )
                .first()
            )
        candidate = self._build_correlation_id(payload)
        return self.get_by_correlation_id(candidate)

    def _find_by_resource(
        self, resource_type: str, resource_id: int
    ) -> ObservabilityCorrelation | None:
        return (
            self.db.query(ObservabilityCorrelation)
            .filter(
                ObservabilityCorrelation.resource_type == resource_type,
                ObservabilityCorrelation.resource_id == resource_id,
            )
            .order_by(ObservabilityCorrelation.id.desc())
            .first()
        )

    def _apply_observation(
        self,
        correlation: ObservabilityCorrelation,
        payload: GitHubCheckRunObservationRequest,
    ) -> None:
        correlation.resource_type = payload.resource_type or correlation.resource_type
        correlation.resource_id = payload.resource_id or correlation.resource_id
        if payload.resource_type and payload.resource_id is not None:
            self._apply_resource_pointer(correlation, payload.resource_type, payload.resource_id)
        correlation.pull_request_id = payload.pull_request_id or correlation.pull_request_id
        correlation.flaky_test_id = payload.flaky_test_id or correlation.flaky_test_id
        correlation.repo_full_name = payload.repo_full_name or correlation.repo_full_name
        correlation.commit_sha = payload.commit_sha or correlation.commit_sha
        correlation.task_id = payload.task_id or correlation.task_id
        correlation.request_id = payload.request_id or correlation.request_id
        correlation.delivery_id = payload.delivery_id or correlation.delivery_id
        correlation.github_check_run_id = (
            payload.github_check_run_id or correlation.github_check_run_id
        )
        correlation.github_check_run_name = (
            payload.github_check_run_name or correlation.github_check_run_name
        )
        correlation.github_check_run_status = (
            payload.github_check_run_status or correlation.github_check_run_status
        )
        correlation.github_check_run_conclusion = (
            payload.github_check_run_conclusion or correlation.github_check_run_conclusion
        )
        correlation.github_check_run_url = (
            payload.github_check_run_url or correlation.github_check_run_url
        )
        correlation.github_workflow_name = (
            payload.github_workflow_name or correlation.github_workflow_name
        )
        correlation.github_job_name = payload.github_job_name or correlation.github_job_name
        correlation.github_run_url = payload.github_run_url or correlation.github_run_url
        correlation.cloudwatch_log_group = (
            payload.cloudwatch_log_group
            or correlation.cloudwatch_log_group
            or self.settings.cloudwatch_log_group
            or None
        )
        correlation.cloudwatch_log_stream = (
            payload.cloudwatch_log_stream or correlation.cloudwatch_log_stream
        )
        correlation.cloudwatch_log_url = (
            payload.cloudwatch_log_url or correlation.cloudwatch_log_url
        )
        correlation.event_metadata = {
            **(correlation.event_metadata or {}),
            **payload.event_metadata,
            **get_serialized_log_context(),
        }

    @staticmethod
    def _apply_resource_pointer(
        correlation: ObservabilityCorrelation, resource_type: str, resource_id: int
    ) -> None:
        if resource_type == "pull_request":
            correlation.pull_request_id = resource_id
        if resource_type == "flaky_test_run":
            correlation.flaky_test_id = resource_id

    @staticmethod
    def _resolve_flaky_repo_full_name(payload: FlakyTestTriageRequest) -> str | None:
        if payload.repo_full_name:
            return payload.repo_full_name
        if payload.ci_provider == "github_actions" and "/" in payload.suite_name:
            return payload.suite_name
        return None

    @staticmethod
    def _build_cloudwatch_filter_pattern(
        correlation: ObservabilityCorrelation,
    ) -> str | None:
        candidates = (
            correlation.task_id,
            correlation.request_id,
            correlation.delivery_id,
            str(correlation.github_check_run_id) if correlation.github_check_run_id else None,
            correlation.correlation_id,
        )
        for candidate in candidates:
            if candidate and candidate.strip():
                return f'"{candidate.strip()}"'
        return None

    @staticmethod
    def _build_correlation_id(payload: GitHubCheckRunObservationRequest) -> str:
        if payload.request_id:
            return f"request:{payload.request_id}"
        if payload.delivery_id:
            return f"delivery:{payload.delivery_id}"
        if payload.task_id:
            return f"task:{payload.task_id}"
        if payload.resource_type and payload.resource_id is not None:
            return f"{payload.resource_type}:{payload.resource_id}"
        if payload.github_check_run_id is not None:
            return f"github_check_run:{payload.github_check_run_id}"
        return f"correlation:{uuid.uuid4().hex}"
