import hashlib
import hmac
import json
from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.api.routes import get_task_dispatcher
from app.core.config import get_settings
from app.core.log_context import bind_log_context, clear_log_context
from app.models.flaky_test import FlakyTestRun
from app.models.pull_request import PullRequestAnalysis, PullRequestRecord
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.schemas.pull_request import PullRequestAnalyzeRequest
from app.services.async_dispatch import AsyncDispatchResult
from app.services.exceptions import (
    GitHubPullRequestContentError,
    InvalidWebhookPayloadError,
    LLMProviderConfigurationError,
    LLMProviderInvocationError,
    TaskDispatchError,
)
from app.services.flaky_triage import FlakyTestService
from app.services.github import GitHubWebhookService
from app.services.github_app_auth import GitHubAppAuthService
from app.services.github_pr_content import GitHubPullRequestContentService
from app.services.llm import LLMAnalysisResult, LLMClient, OpenAILLMProvider
from app.services.llm_prompts import LLMPromptBuilder, PromptSet
from app.services.pr_analysis import WEBHOOK_DIFF_PLACEHOLDER, PullRequestService
from app.services.sqs_step_functions_dispatcher import SqsStepFunctionsDispatcher
from app.services.step_functions_dispatcher import StepFunctionsDispatcher
from app.services.task_dispatcher import TaskDispatcher
from app.services.workflows import (
    FlakyTestWorkflowService,
    GitHubWebhookWorkflowService,
    PullRequestAnalysisWorkflowService,
)
from app.tasks.pr_analysis import analyze_pull_request_task


def make_signature(service: GitHubWebhookService, raw_body: bytes) -> str:
    secret = service.settings.github_webhook_secret
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


class DeterministicPRLLMClient:
    provider_name = "mock"

    def analyze_pull_request(self, diff_text: str, title: str) -> LLMAnalysisResult:
        return LLMAnalysisResult(
            summary=f"PR '{title}' changes {len(diff_text.splitlines())} diff lines.",
            risks=(
                "Potential regression around error handling, database writes, "
                "and edge-case retries."
            ),
            suggested_tests=(
                "1. Add success-path regression test.\n"
                "2. Add failure-path test for invalid inputs.\n"
                "3. Add integration test covering retry/idempotency behavior."
            ),
        )


class DeterministicFlakyLLMClient:
    provider_name = "mock"

    def triage_flaky_test(self, test_name: str, failure_log: str) -> object:
        return type(
            "TriageResult",
            (),
            {
                "cluster_key": f"cluster:{test_name}",
                "suspected_root_cause": (
                    "Likely timeout under CI load caused the operation to exceed its deadline."
                ),
                "suggested_fix": "Increase timeout thresholds and stabilize async retry timing.",
            },
        )()


def test_task_dispatcher_forwards_current_log_context_to_celery_headers() -> None:
    dispatcher = TaskDispatcher()
    original_apply_async = analyze_pull_request_task.apply_async
    captured: dict[str, object] = {}

    class FakeAsyncResult:
        id = "celery-task-123"

    def fake_apply_async(*, args: list[int], headers: dict[str, str]) -> FakeAsyncResult:
        captured["args"] = args
        captured["headers"] = headers
        return FakeAsyncResult()

    analyze_pull_request_task.apply_async = fake_apply_async  # type: ignore[method-assign]
    try:
        clear_log_context()
        with bind_log_context(request_id="req-123", delivery_id="delivery-123"):
            task_id = dispatcher.dispatch_pull_request_analysis(42)
    finally:
        analyze_pull_request_task.apply_async = original_apply_async  # type: ignore[method-assign]
        clear_log_context()

    assert captured["args"] == [42]
    assert captured["headers"] == {
        "request_id": "req-123",
        "delivery_id": "delivery-123",
    }
    assert task_id.task_id == "celery-task-123"
    assert task_id.backend_name == "celery"


def test_step_functions_dispatcher_starts_execution_with_trace_context() -> None:
    captured: dict[str, object] = {}
    expected_arn = "arn:aws:states:us-east-1:123456789012:stateMachine:devaccel-analysis"

    class FakeStepFunctionsClient:
        def start_execution(self, **kwargs: object) -> dict[str, str]:
            captured.update(kwargs)
            return {"executionArn": "arn:aws:states:execution:devaccel:123"}

    settings = get_settings()
    original_arn = settings.step_functions_state_machine_arn
    original_pr_arn = settings.step_functions_pr_analysis_state_machine_arn
    settings.step_functions_state_machine_arn = expected_arn
    settings.step_functions_pr_analysis_state_machine_arn = expected_arn

    try:
        clear_log_context()
        dispatcher = StepFunctionsDispatcher(client=FakeStepFunctionsClient(), settings=settings)
        with bind_log_context(request_id="req-123", delivery_id="delivery-123"):
            result = dispatcher.dispatch_pull_request_analysis(42)
    finally:
        settings.step_functions_state_machine_arn = original_arn
        settings.step_functions_pr_analysis_state_machine_arn = original_pr_arn
        clear_log_context()

    assert captured["stateMachineArn"] == expected_arn
    payload = json.loads(captured["input"])
    assert payload == {
        "workflow_name": "pull_request_analysis",
        "resource_type": "pull_request",
        "resource_id": 42,
        "trace_context": {
            "request_id": "req-123",
            "delivery_id": "delivery-123",
        },
    }
    assert result.task_id == "arn:aws:states:execution:devaccel:123"
    assert result.backend_name == "step_functions"


def test_step_functions_dispatcher_uses_workflow_specific_state_machine_arn_for_flaky_triage() -> (
    None
):
    captured: dict[str, object] = {}

    class FakeStepFunctionsClient:
        def start_execution(self, **kwargs: object) -> dict[str, str]:
            captured.update(kwargs)
            return {"executionArn": "arn:aws:states:execution:devaccel:flaky-123"}

    settings = get_settings()
    original_arn = settings.step_functions_state_machine_arn
    original_flaky_arn = settings.step_functions_flaky_triage_state_machine_arn
    settings.step_functions_state_machine_arn = "arn:aws:states:generic"
    settings.step_functions_flaky_triage_state_machine_arn = (
        "arn:aws:states:us-east-1:123456789012:stateMachine:devaccel-flaky-triage"
    )

    try:
        clear_log_context()
        dispatcher = StepFunctionsDispatcher(client=FakeStepFunctionsClient(), settings=settings)
        result = dispatcher.dispatch_flaky_test_triage(7)
    finally:
        settings.step_functions_state_machine_arn = original_arn
        settings.step_functions_flaky_triage_state_machine_arn = original_flaky_arn
        clear_log_context()

    assert (
        captured["stateMachineArn"]
        == "arn:aws:states:us-east-1:123456789012:stateMachine:devaccel-flaky-triage"
    )
    payload = json.loads(captured["input"])
    assert payload["workflow_name"] == "flaky_test_triage"
    assert payload["resource_type"] == "flaky_test_run"
    assert payload["resource_id"] == 7
    assert result.task_id == "arn:aws:states:execution:devaccel:flaky-123"


def test_get_task_dispatcher_uses_step_functions_backend_when_configured() -> None:
    settings = get_settings()
    original_backend = settings.async_dispatch_backend
    settings.async_dispatch_backend = "step_functions"

    try:
        dispatcher = get_task_dispatcher()
    finally:
        settings.async_dispatch_backend = original_backend

    assert isinstance(dispatcher, StepFunctionsDispatcher)


def test_sqs_step_functions_dispatcher_sends_start_execution_message() -> None:
    captured: dict[str, object] = {}

    class FakeSQSClient:
        def send_message(self, **kwargs: object) -> dict[str, str]:
            captured.update(kwargs)
            return {"MessageId": "sqs-message-123"}

    settings = get_settings()
    original_queue_url = settings.sqs_queue_url
    original_arn = settings.step_functions_pr_analysis_state_machine_arn
    settings.sqs_queue_url = "https://sqs.us-east-1.amazonaws.com/123456789012/devaccel-analysis"
    settings.step_functions_pr_analysis_state_machine_arn = (
        "arn:aws:states:us-east-1:123456789012:stateMachine:devaccel-pr-analysis"
    )

    try:
        clear_log_context()
        dispatcher = SqsStepFunctionsDispatcher(client=FakeSQSClient(), settings=settings)
        with bind_log_context(request_id="req-123", delivery_id="delivery-123"):
            result = dispatcher.dispatch_pull_request_analysis(42)
    finally:
        settings.sqs_queue_url = original_queue_url
        settings.step_functions_pr_analysis_state_machine_arn = original_arn
        clear_log_context()

    assert (
        captured["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789012/devaccel-analysis"
    )
    message = json.loads(captured["MessageBody"])
    assert message["message_type"] == "start_step_function_execution"
    assert (
        message["state_machine_arn"]
        == "arn:aws:states:us-east-1:123456789012:stateMachine:devaccel-pr-analysis"
    )
    assert message["execution_input"] == {
        "workflow_name": "pull_request_analysis",
        "resource_type": "pull_request",
        "resource_id": 42,
        "trace_context": {
            "request_id": "req-123",
            "delivery_id": "delivery-123",
        },
    }
    assert result.task_id == "sqs-message-123"
    assert result.backend_name == "sqs_step_functions"


def test_get_task_dispatcher_uses_sqs_step_functions_backend_when_configured() -> None:
    settings = get_settings()
    original_backend = settings.async_dispatch_backend
    settings.async_dispatch_backend = "sqs_step_functions"

    try:
        dispatcher = get_task_dispatcher()
    finally:
        settings.async_dispatch_backend = original_backend

    assert isinstance(dispatcher, SqsStepFunctionsDispatcher)


def test_pr_service_create_and_process_analysis(db_session: Session) -> None:
    # 这是“service 层的核心业务测试”。
    # 最合适出现的阶段：
    # 1. 你已经有 model
    # 2. 你已经有 schema
    # 3. 你已经有 service
    # 4. 但 route / Celery 还可以晚一点再测
    try:
        service = PullRequestService(db_session, llm_client=DeterministicPRLLMClient())  # type: ignore[arg-type]
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
        )

        record = service.create_analysis_job(payload)
        assert record.id is not None
        assert record.status == "queued"

        processed = service.process_analysis(record.id)
        assert processed.status == "completed"

        analysis = db_session.query(PullRequestAnalysis).filter_by(pull_request_id=record.id).one()
        assert "PR 'Refactor payment retry flow'" in analysis.summary
        assert analysis.model_provider == "mock"
    finally:
        pass


def test_pr_service_process_analysis_fetches_patch_bundle_for_webhook_placeholder(
    db_session: Session,
) -> None:
    try:
        github_content_service = Mock()
        github_content_service.fetch_pull_request_patch_bundle.return_value = (
            "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-print('old')\n+print('new')"
        )
        service = PullRequestService(
            db_session,
            llm_client=DeterministicPRLLMClient(),  # type: ignore[arg-type]
            github_content_service=github_content_service,
        )
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            installation_id=98765,
            diff_text=WEBHOOK_DIFF_PLACEHOLDER,
        )

        record = service.create_analysis_job(payload)
        processed = service.process_analysis(record.id)

        assert processed.status == "completed"
        refreshed = db_session.get(PullRequestRecord, record.id)
        assert refreshed is not None
        assert "diff --git a/app.py b/app.py" in refreshed.diff_text
        github_content_service.fetch_pull_request_patch_bundle.assert_called_once_with(
            "acme/payments",
            42,
            installation_id=98765,
        )
    finally:
        pass


def test_pr_service_get_analysis_loads_related_analyses(db_session: Session) -> None:
    try:
        record = PullRequestRecord(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
            status="completed",
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        db_session.add(
            PullRequestAnalysis(
                pull_request_id=record.id,
                summary="PR analysis summary",
                risks="PR analysis risks",
                suggested_tests="PR analysis suggested tests",
                model_provider="mock",
            )
        )
        db_session.commit()

        service = PullRequestService(db_session)
        loaded = service.get_analysis(record.id)

        assert loaded is not None
        assert loaded.id == record.id
        assert len(loaded.analyses) == 1
        assert loaded.analyses[0].summary == "PR analysis summary"
    finally:
        pass


def test_pr_service_persists_provider_name_from_llm_client(db_session: Session) -> None:
    class FakeLLMClient:
        provider_name = "fake-provider"

        def analyze_pull_request(self, diff_text: str, title: str) -> LLMAnalysisResult:
            return LLMAnalysisResult(
                summary=f"summary for {title}",
                risks=f"risks for {len(diff_text.splitlines())} lines",
                suggested_tests="1. smoke\n2. regression",
            )

    try:
        service = PullRequestService(db_session, llm_client=FakeLLMClient())  # type: ignore[arg-type]
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
        )

        record = service.create_analysis_job(payload)
        service.process_analysis(record.id)

        analysis = db_session.query(PullRequestAnalysis).filter_by(pull_request_id=record.id).one()
        assert analysis.model_provider == "fake-provider"
    finally:
        pass


def test_flaky_service_create_and_process_triage(db_session: Session) -> None:
    # 这同样是“service 层业务测试”。
    # 最合适出现的阶段：
    # 1. flaky 的 model / schema / service 已经搭好
    # 2. 想先确认 triage 核心流程正确
    # 3. 还没有把 HTTP / Celery 全部卷进来
    try:
        service = FlakyTestService(db_session, llm_client=DeterministicFlakyLLMClient())  # type: ignore[arg-type]
        payload = FlakyTestTriageRequest(
            test_name="test_retry_payment_timeout",
            suite_name="payments.integration",
            branch_name="main",
            ci_provider="github_actions",
            workflow_name="CI",
            job_name="pytest",
            run_url="https://github.com/acme/payments/actions/runs/123",
            commit_sha="abc123def456",
            failure_log="TimeoutError: operation exceeded 30 seconds",
        )

        run = service.create_triage_job(payload)
        assert run.id is not None
        assert run.status == "queued"

        processed = service.process_triage(run.id)
        assert processed.status == "completed"
        assert processed.cluster_key == "cluster:test_retry_payment_timeout"
        assert "timeout" in processed.suspected_root_cause.lower()

        stored = db_session.query(FlakyTestRun).filter_by(id=run.id).one()
        assert stored.suggested_fix != ""
        assert stored.error_message is None
        assert stored.ci_provider == "github_actions"
        assert stored.workflow_name == "CI"
        assert stored.job_name == "pytest"
        assert stored.run_url == "https://github.com/acme/payments/actions/runs/123"
        assert stored.commit_sha == "abc123def456"
    finally:
        pass


def test_flaky_service_canonicalizes_cluster_key_before_persisting(db_session: Session) -> None:
    class DriftedClusterLLMClient:
        provider_name = "openai"

        def triage_flaky_test(self, test_name: str, failure_log: str) -> object:
            del test_name, failure_log
            return type(
                "TriageResult",
                (),
                {
                    "cluster_key": "Payment Retries Timeout",
                    "suspected_root_cause": "Timeout under CI load.",
                    "suggested_fix": "Stabilize retry timing.",
                },
            )()

    service = FlakyTestService(db_session, llm_client=DriftedClusterLLMClient())  # type: ignore[arg-type]
    payload = FlakyTestTriageRequest(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
    )

    run = service.create_triage_job(payload)
    processed = service.process_triage(run.id)

    assert processed.cluster_key == "cluster:payment_retries_timeout"


def test_flaky_service_falls_back_to_test_name_when_cluster_key_is_placeholder(
    db_session: Session,
) -> None:
    class PlaceholderClusterLLMClient:
        provider_name = "openai"

        def triage_flaky_test(self, test_name: str, failure_log: str) -> object:
            del test_name, failure_log
            return type(
                "TriageResult",
                (),
                {
                    "cluster_key": "pending",
                    "suspected_root_cause": "Timeout under CI load.",
                    "suggested_fix": "Stabilize retry timing.",
                },
            )()

    service = FlakyTestService(db_session, llm_client=PlaceholderClusterLLMClient())  # type: ignore[arg-type]
    payload = FlakyTestTriageRequest(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
    )

    run = service.create_triage_job(payload)
    processed = service.process_triage(run.id)

    assert processed.cluster_key == "cluster:test_retry_payment_timeout"


def test_flaky_service_reuses_similar_historical_cluster_key(db_session: Session) -> None:
    historical = FlakyTestRun(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
        status="completed",
        cluster_key="cluster:timeout_under_ci_load",
        suspected_root_cause="CI load spikes requests.",
        suggested_fix="Increase explicit waits.",
    )
    db_session.add(historical)
    db_session.commit()

    class SimilarClusterLLMClient:
        provider_name = "openai"

        def triage_flaky_test(self, test_name: str, failure_log: str) -> object:
            del test_name, failure_log
            return type(
                "TriageResult",
                (),
                {
                    "cluster_key": "Timeout CI Load",
                    "suspected_root_cause": "CI load spikes requests.",
                    "suggested_fix": "Increase explicit waits.",
                },
            )()

    service = FlakyTestService(db_session, llm_client=SimilarClusterLLMClient())  # type: ignore[arg-type]
    payload = FlakyTestTriageRequest(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
    )

    run = service.create_triage_job(payload)
    processed = service.process_triage(run.id)

    assert processed.cluster_key == "cluster:timeout_under_ci_load"


def test_prompt_builder_guides_flaky_cluster_key_toward_stable_snake_case() -> None:
    prompt = LLMPromptBuilder().build_flaky_test_triage_prompt(
        "test_retry_payment_timeout",
        "TimeoutError: operation exceeded 30 seconds",
    )

    assert "short stable snake_case category" in prompt.system_prompt
    assert "no 'cluster:' prefix" in prompt.system_prompt
    assert "reused across similar failures" in prompt.user_prompt


def test_pr_service_marks_record_failed_when_llm_invocation_fails(db_session: Session) -> None:
    class FailingLLMClient:
        provider_name = "openai"

        def analyze_pull_request(self, diff_text: str, title: str) -> LLMAnalysisResult:
            raise LLMProviderInvocationError("OpenAI request failed: timeout")

    service = PullRequestService(db_session, llm_client=FailingLLMClient())  # type: ignore[arg-type]
    payload = PullRequestAnalyzeRequest(
        repo_full_name="acme/payments",
        pr_number=42,
        title="Refactor payment retry flow",
        author="alice",
        diff_text="+++ services/payment.py\n+ retry_count += 1",
    )

    record = service.create_analysis_job(payload)

    try:
        service.process_analysis(record.id)
    except LLMProviderInvocationError as exc:
        assert "timeout" in str(exc)
    else:
        raise AssertionError("Expected LLMProviderInvocationError from failing LLM client")

    failed = db_session.get(PullRequestRecord, record.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "OpenAI request failed: timeout"


def test_flaky_service_marks_run_failed_when_llm_invocation_fails(db_session: Session) -> None:
    class FailingLLMClient:
        provider_name = "openai"

        def triage_flaky_test(self, test_name: str, failure_log: str) -> object:
            raise LLMProviderInvocationError("OpenAI response was not valid JSON")

    service = FlakyTestService(db_session, llm_client=FailingLLMClient())  # type: ignore[arg-type]
    payload = FlakyTestTriageRequest(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
    )

    run = service.create_triage_job(payload)

    try:
        service.process_triage(run.id)
    except LLMProviderInvocationError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("Expected LLMProviderInvocationError from failing flaky LLM client")

    failed = db_session.get(FlakyTestRun, run.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "OpenAI response was not valid JSON"


def test_github_pr_content_service_builds_patch_bundle_from_file_patches() -> None:
    class FakeResponse:
        def __init__(self, status_code: int, payload: object) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def get(self, url: str, headers: dict[str, str], params: dict[str, object]) -> FakeResponse:
            self.calls.append((url, params))
            if params["page"] == 1:
                return FakeResponse(
                    200,
                    [
                        {
                            "filename": "app/services/payment.py",
                            "status": "modified",
                            "patch": "@@ -1 +1 @@\n-old\n+new",
                        },
                        {
                            "filename": "assets/logo.png",
                            "status": "modified",
                        },
                    ],
                )
            return FakeResponse(200, [])

    client = FakeClient()
    service = GitHubPullRequestContentService(client=client)  # type: ignore[arg-type]

    bundle = service.fetch_pull_request_patch_bundle("acme/payments", 42)

    assert "diff --git a/app/services/payment.py b/app/services/payment.py" in bundle
    assert "# file_status: modified" in bundle
    assert "@@ -1 +1 @@" in bundle
    assert "assets/logo.png" not in bundle


def test_github_pr_content_service_uses_installation_token_when_installation_id_is_present() -> (
    None
):
    class FakeResponse:
        def __init__(self, status_code: int, payload: object) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeClient:
        def __init__(self) -> None:
            self.last_headers: dict[str, str] | None = None

        def get(self, url: str, headers: dict[str, str], params: dict[str, object]) -> FakeResponse:
            self.last_headers = headers
            if params["page"] == 1:
                return FakeResponse(
                    200,
                    [
                        {
                            "filename": "app/services/payment.py",
                            "status": "modified",
                            "patch": "@@ -1 +1 @@\n-old\n+new",
                        }
                    ],
                )
            return FakeResponse(200, [])

    auth_service = Mock()
    auth_service.get_installation_access_token.return_value = "installation-token"
    client = FakeClient()
    service = GitHubPullRequestContentService(
        client=client,  # type: ignore[arg-type]
        app_auth_service=auth_service,
    )

    service.fetch_pull_request_patch_bundle("acme/payments", 42, installation_id=999)

    assert client.last_headers is not None
    assert client.last_headers["Authorization"] == "Bearer installation-token"
    auth_service.get_installation_access_token.assert_called_once_with(999)


def test_llm_client_uses_prompt_builder_and_provider() -> None:
    class FakePromptBuilder(LLMPromptBuilder):
        def build_pull_request_analysis_prompt(self, diff_text: str, title: str) -> PromptSet:
            return PromptSet(
                system_prompt="system prompt",
                user_prompt=f"title={title}; diff_lines={len(diff_text.splitlines())}",
            )

    class FakeProvider:
        provider_name = "fake-provider"

        def __init__(self) -> None:
            self.last_prompt: PromptSet | None = None

        def analyze_pull_request(
            self, prompt: PromptSet, *, diff_text: str, title: str
        ) -> LLMAnalysisResult:
            self.last_prompt = prompt
            return LLMAnalysisResult(
                summary=f"provider summary for {title}",
                risks=f"provider risks for {len(diff_text.splitlines())} lines",
                suggested_tests="1. provider test",
            )

        def triage_flaky_test(
            self, prompt: PromptSet, *, test_name: str, failure_log: str
        ) -> object:
            raise AssertionError("This test should not call triage_flaky_test")

    provider = FakeProvider()
    client = LLMClient(provider=provider, prompt_builder=FakePromptBuilder())

    result = client.analyze_pull_request(
        "+++ services/payment.py\n+ retry_count += 1",
        "Refactor payment retry flow",
    )

    assert provider.last_prompt is not None
    assert provider.last_prompt.system_prompt == "system prompt"
    assert "title=Refactor payment retry flow" in provider.last_prompt.user_prompt
    assert client.provider_name == "fake-provider"
    assert result.summary == "provider summary for Refactor payment retry flow"


def test_llm_client_rejects_provider_names_that_are_not_wired_yet() -> None:
    try:
        LLMClient(provider_name="bedrock")
    except LLMProviderConfigurationError as exc:
        assert "not wired yet" in str(exc)
    else:
        raise AssertionError(
            "Expected LLMProviderConfigurationError for bedrock provider selection"
        )


def test_openai_provider_parses_pull_request_analysis_json() -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.output_parsed = type(
                "ParsedPayload",
                (),
                {
                    "summary": "summary text",
                    "risks": "risk text",
                    "suggested_tests": "1. test",
                },
            )()

    class FakeResponsesAPI:
        def __init__(self) -> None:
            self.last_kwargs: dict[str, object] | None = None

        def parse(self, **kwargs: object) -> FakeResponse:
            self.last_kwargs = kwargs
            return FakeResponse()

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.responses = FakeResponsesAPI()

    fake_client = FakeOpenAIClient()
    provider = OpenAILLMProvider(client=fake_client, model="gpt-4o-mini")  # type: ignore[arg-type]

    result = provider.analyze_pull_request(
        PromptSet(system_prompt="system", user_prompt="user"),
        diff_text="+++ file.py\n+ change",
        title="Refactor payment retry flow",
    )

    assert fake_client.responses.last_kwargs is not None
    assert fake_client.responses.last_kwargs["model"] == "gpt-4o-mini"
    assert fake_client.responses.last_kwargs["instructions"] == "system"
    assert fake_client.responses.last_kwargs["input"] == "user"
    assert (
        fake_client.responses.last_kwargs["text_format"].__name__ == "_PullRequestAnalysisPayload"
    )
    assert result.summary == "summary text"
    assert result.risks == "risk text"
    assert result.suggested_tests == "1. test"


def test_openai_provider_rejects_missing_structured_output() -> None:
    class FakeResponse:
        output_parsed = None

    class FakeResponsesAPI:
        def parse(self, **kwargs: object) -> FakeResponse:
            return FakeResponse()

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.responses = FakeResponsesAPI()

    provider = OpenAILLMProvider(client=FakeOpenAIClient(), model="gpt-4o-mini")  # type: ignore[arg-type]

    try:
        provider.triage_flaky_test(
            PromptSet(system_prompt="system", user_prompt="user"),
            test_name="test_retry_payment_timeout",
            failure_log="TimeoutError",
        )
    except LLMProviderInvocationError as exc:
        assert "expected schema" in str(exc)
    else:
        raise AssertionError("Expected LLMProviderInvocationError for missing structured output")


def test_github_app_auth_service_returns_cached_token_before_expiry() -> None:
    service = GitHubAppAuthService(client=Mock())
    service._token_cache[123] = ("cached-token", None)

    token = service.get_installation_access_token(123)

    assert token == "cached-token"


def test_github_app_auth_service_wraps_missing_private_key_file() -> None:
    service = GitHubAppAuthService(client=Mock())
    service.settings.github_app_id = "123456"
    service.settings.github_private_key_path = "/definitely/missing/github-app.pem"

    try:
        service.get_installation_access_token(999)
    except GitHubPullRequestContentError as exc:
        assert "private key file could not be read" in str(exc)
    else:
        raise AssertionError("Expected GitHubPullRequestContentError for missing private key file")


def test_github_webhook_service_returns_internal_request_for_supported_event() -> None:
    service = GitHubWebhookService()
    raw_body = b"{}"

    payload = {
        "action": "opened",
        "number": 42,
        "installation": {"id": 98765},
        "pull_request": {
            "title": "Refactor payment retry flow",
            "user": {"login": "alice"},
            "body": "This is a PR description, not a diff.",
        },
        "repository": {"full_name": "acme/payments"},
    }

    request = service.handle_event(
        event_name="pull_request",
        signature=make_signature(service, raw_body),
        raw_body=raw_body,
        payload=payload,
    )

    assert request is not None
    assert request.repo_full_name == "acme/payments"
    assert request.pr_number == 42
    assert request.title == "Refactor payment retry flow"
    assert request.author == "alice"
    assert request.installation_id == 98765
    assert "does not include unified diff text" in request.diff_text


def test_github_webhook_service_ignores_unsupported_events() -> None:
    service = GitHubWebhookService()

    request = service.handle_event(
        event_name="issues",
        signature="",
        raw_body=b"{}",
        payload={},
    )

    assert request is None


def test_github_webhook_service_rejects_missing_required_fields() -> None:
    service = GitHubWebhookService()
    raw_body = b"{}"

    payload = {
        "action": "opened",
        "installation": {"id": 98765},
        "pull_request": {
            "title": "Refactor payment retry flow",
            "user": {"login": "alice"},
        },
        "repository": {"full_name": "acme/payments"},
    }

    try:
        service.handle_event(
            event_name="pull_request",
            signature=make_signature(service, raw_body),
            raw_body=raw_body,
            payload=payload,
        )
    except InvalidWebhookPayloadError as exc:
        assert "number" in str(exc)
    else:
        raise AssertionError("Expected InvalidWebhookPayloadError for invalid webhook payload")


def test_github_webhook_service_requires_installation_id() -> None:
    service = GitHubWebhookService()
    raw_body = b"{}"

    payload = {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "title": "Refactor payment retry flow",
            "user": {"login": "alice"},
        },
        "repository": {"full_name": "acme/payments"},
    }

    try:
        service.handle_event(
            event_name="pull_request",
            signature=make_signature(service, raw_body),
            raw_body=raw_body,
            payload=payload,
        )
    except InvalidWebhookPayloadError as exc:
        assert "installation" in str(exc)
    else:
        raise AssertionError("Expected InvalidWebhookPayloadError when installation is missing")


def test_pull_request_workflow_enqueues_job_and_dispatches_task(db_session: Session) -> None:
    try:
        pr_service = PullRequestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_pull_request_analysis.return_value = AsyncDispatchResult(
            task_id="task-pr-123",
            backend_name="celery",
        )
        workflow = PullRequestAnalysisWorkflowService(pr_service=pr_service, dispatcher=dispatcher)
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            installation_id=98765,
            diff_text="+++ services/payment.py\n+ retry_count += 1",
        )

        record = workflow.enqueue_analysis(payload)

        assert record.id is not None
        assert record.status == "queued"
        dispatcher.dispatch_pull_request_analysis.assert_called_once_with(record.id)
    finally:
        pass


def test_pull_request_workflow_handles_github_webhook_and_dispatches_task(
    db_session: Session,
) -> None:
    try:
        pr_service = PullRequestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_pull_request_analysis.return_value = AsyncDispatchResult(
            task_id="task-pr-123",
            backend_name="celery",
        )
        webhook_service = GitHubWebhookService()
        raw_body = b"{}"
        pr_workflow = PullRequestAnalysisWorkflowService(
            pr_service=pr_service,
            dispatcher=dispatcher,
        )
        workflow = GitHubWebhookWorkflowService(
            github_webhook_service=webhook_service,
            pr_analysis_workflow=pr_workflow,
        )
        payload = {
            "action": "opened",
            "number": 42,
            "installation": {"id": 98765},
            "pull_request": {
                "title": "Refactor payment retry flow",
                "user": {"login": "alice"},
            },
            "repository": {"full_name": "acme/payments"},
        }

        record = workflow.handle_webhook(
            event_name="pull_request",
            signature=make_signature(webhook_service, raw_body),
            raw_body=raw_body,
            payload=payload,
            delivery_id="delivery-123",
        )

        assert record is not None
        assert record.repo_full_name == "acme/payments"
        assert record.delivery_id == "delivery-123"
        dispatcher.dispatch_pull_request_analysis.assert_called_once_with(record.id)
    finally:
        pass


def test_flaky_test_workflow_enqueues_job_and_dispatches_task(db_session: Session) -> None:
    try:
        flaky_service = FlakyTestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_flaky_test_triage.return_value = AsyncDispatchResult(
            task_id="task-flaky-123",
            backend_name="celery",
        )
        workflow = FlakyTestWorkflowService(flaky_test_service=flaky_service, dispatcher=dispatcher)
        payload = FlakyTestTriageRequest(
            test_name="test_retry_payment_timeout",
            suite_name="payments.integration",
            branch_name="main",
            failure_log="TimeoutError: operation exceeded 30 seconds",
        )

        run = workflow.enqueue_triage(payload)

        assert run.id is not None
        assert run.status == "queued"
        dispatcher.dispatch_flaky_test_triage.assert_called_once_with(run.id)
    finally:
        pass


def test_pull_request_workflow_marks_dispatch_failed_when_dispatcher_raises(
    db_session: Session,
) -> None:
    try:
        pr_service = PullRequestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_pull_request_analysis.side_effect = RuntimeError("broker unavailable")
        workflow = PullRequestAnalysisWorkflowService(pr_service=pr_service, dispatcher=dispatcher)
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
        )

        try:
            workflow.enqueue_analysis(payload)
        except TaskDispatchError:
            pass
        else:
            raise AssertionError("Expected TaskDispatchError when dispatcher fails")

        stored = db_session.query(PullRequestRecord).one()
        assert stored.status == "dispatch_failed"
        assert stored.error_message == "broker unavailable"
    finally:
        pass


def test_flaky_test_workflow_marks_dispatch_failed_when_dispatcher_raises(
    db_session: Session,
) -> None:
    try:
        flaky_service = FlakyTestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_flaky_test_triage.side_effect = RuntimeError("broker unavailable")
        workflow = FlakyTestWorkflowService(flaky_test_service=flaky_service, dispatcher=dispatcher)
        payload = FlakyTestTriageRequest(
            test_name="test_retry_payment_timeout",
            suite_name="payments.integration",
            branch_name="main",
            failure_log="TimeoutError: operation exceeded 30 seconds",
        )

        try:
            workflow.enqueue_triage(payload)
        except TaskDispatchError:
            pass
        else:
            raise AssertionError("Expected TaskDispatchError when dispatcher fails")

        stored = db_session.query(FlakyTestRun).one()
        assert stored.status == "dispatch_failed"
        assert stored.error_message == "broker unavailable"
    finally:
        pass


def test_github_webhook_workflow_reuses_existing_record_for_same_delivery_id(
    db_session: Session,
) -> None:
    try:
        pr_service = PullRequestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_pull_request_analysis.return_value = AsyncDispatchResult(
            task_id="task-pr-123",
            backend_name="celery",
        )
        webhook_service = GitHubWebhookService()
        raw_body = b"{}"
        pr_workflow = PullRequestAnalysisWorkflowService(
            pr_service=pr_service,
            dispatcher=dispatcher,
        )
        workflow = GitHubWebhookWorkflowService(
            github_webhook_service=webhook_service,
            pr_analysis_workflow=pr_workflow,
        )
        payload = {
            "action": "opened",
            "number": 42,
            "installation": {"id": 98765},
            "pull_request": {
                "title": "Refactor payment retry flow",
                "user": {"login": "alice"},
            },
            "repository": {"full_name": "acme/payments"},
        }

        first = workflow.handle_webhook(
            event_name="pull_request",
            signature=make_signature(webhook_service, raw_body),
            raw_body=raw_body,
            payload=payload,
            delivery_id="delivery-duplicate",
        )
        second = workflow.handle_webhook(
            event_name="pull_request",
            signature=make_signature(webhook_service, raw_body),
            raw_body=raw_body,
            payload=payload,
            delivery_id="delivery-duplicate",
        )

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert db_session.query(PullRequestRecord).count() == 1
        dispatcher.dispatch_pull_request_analysis.assert_called_once_with(first.id)
    finally:
        pass
