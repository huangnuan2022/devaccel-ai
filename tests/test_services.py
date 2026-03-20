import hashlib
import hmac
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.flaky_test import FlakyTestRun
from app.models.pull_request import PullRequestAnalysis, PullRequestRecord
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.schemas.pull_request import PullRequestAnalyzeRequest
from app.services.exceptions import InvalidWebhookPayloadError, TaskDispatchError
from app.services.flaky_triage import FlakyTestService
from app.services.github import GitHubWebhookService
from app.services.github_pr_content import GitHubPullRequestContentService
from app.services.pr_analysis import PullRequestService, WEBHOOK_DIFF_PLACEHOLDER
from app.services.workflows import (
    FlakyTestWorkflowService,
    GitHubWebhookWorkflowService,
    PullRequestAnalysisWorkflowService,
)


def make_test_db() -> Session:
    # 这类测试属于“service 层单元 / 轻集成测试”。
    # 在真实工程里，通常应该出现在：
    # 1. model 和 service 层已经稳定
    # 2. route 还没大规模铺开之前，或 route 同步推进时
    #
    # 它的价值是：
    # 1. 先验证业务逻辑对不对
    # 2. 不把 HTTP 框架细节混进来
    # 3. 出问题时更容易定位在业务层
    engine = create_engine("sqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def make_signature(service: GitHubWebhookService, raw_body: bytes) -> str:
    secret = service.settings.github_webhook_secret
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def test_pr_service_create_and_process_analysis() -> None:
    # 这是“service 层的核心业务测试”。
    # 最合适出现的阶段：
    # 1. 你已经有 model
    # 2. 你已经有 schema
    # 3. 你已经有 service
    # 4. 但 route / Celery 还可以晚一点再测
    db = make_test_db()
    try:
        service = PullRequestService(db)
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

        analysis = db.query(PullRequestAnalysis).filter_by(pull_request_id=record.id).one()
        assert "PR 'Refactor payment retry flow'" in analysis.summary
        assert analysis.model_provider == "mock"
    finally:
        db.close()


def test_pr_service_process_analysis_fetches_patch_bundle_for_webhook_placeholder() -> None:
    db = make_test_db()
    try:
        github_content_service = Mock()
        github_content_service.fetch_pull_request_patch_bundle.return_value = (
            "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-print('old')\n+print('new')"
        )
        service = PullRequestService(db, github_content_service=github_content_service)
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text=WEBHOOK_DIFF_PLACEHOLDER,
        )

        record = service.create_analysis_job(payload)
        processed = service.process_analysis(record.id)

        assert processed.status == "completed"
        refreshed = db.get(PullRequestRecord, record.id)
        assert refreshed is not None
        assert "diff --git a/app.py b/app.py" in refreshed.diff_text
        github_content_service.fetch_pull_request_patch_bundle.assert_called_once_with(
            "acme/payments",
            42,
        )
    finally:
        db.close()


def test_pr_service_get_analysis_loads_related_analyses() -> None:
    db = make_test_db()
    try:
        record = PullRequestRecord(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
            status="completed",
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        db.add(
            PullRequestAnalysis(
                pull_request_id=record.id,
                summary="PR analysis summary",
                risks="PR analysis risks",
                suggested_tests="PR analysis suggested tests",
                model_provider="mock",
            )
        )
        db.commit()

        service = PullRequestService(db)
        loaded = service.get_analysis(record.id)

        assert loaded is not None
        assert loaded.id == record.id
        assert len(loaded.analyses) == 1
        assert loaded.analyses[0].summary == "PR analysis summary"
    finally:
        db.close()


def test_flaky_service_create_and_process_triage() -> None:
    # 这同样是“service 层业务测试”。
    # 最合适出现的阶段：
    # 1. flaky 的 model / schema / service 已经搭好
    # 2. 想先确认 triage 核心流程正确
    # 3. 还没有把 HTTP / Celery 全部卷进来
    db = make_test_db()
    try:
        service = FlakyTestService(db)
        payload = FlakyTestTriageRequest(
            test_name="test_retry_payment_timeout",
            suite_name="payments.integration",
            branch_name="main",
            failure_log="TimeoutError: operation exceeded 30 seconds",
        )

        run = service.create_triage_job(payload)
        assert run.id is not None
        assert run.status == "queued"

        processed = service.process_triage(run.id)
        assert processed.status == "completed"
        assert processed.cluster_key == "cluster:test_retry_payment_timeout"
        assert "timeout" in processed.suspected_root_cause.lower()

        stored = db.query(FlakyTestRun).filter_by(id=run.id).one()
        assert stored.suggested_fix != ""
    finally:
        db.close()


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


def test_github_webhook_service_returns_internal_request_for_supported_event() -> None:
    service = GitHubWebhookService()
    raw_body = b"{}"

    payload = {
        "action": "opened",
        "number": 42,
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


def test_pull_request_workflow_enqueues_job_and_dispatches_task() -> None:
    db = make_test_db()
    try:
        pr_service = PullRequestService(db)
        dispatcher = Mock()
        workflow = PullRequestAnalysisWorkflowService(pr_service=pr_service, dispatcher=dispatcher)
        payload = PullRequestAnalyzeRequest(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
        )

        record = workflow.enqueue_analysis(payload)

        assert record.id is not None
        assert record.status == "queued"
        dispatcher.dispatch_pull_request_analysis.assert_called_once_with(record.id)
    finally:
        db.close()


def test_pull_request_workflow_handles_github_webhook_and_dispatches_task() -> None:
    db = make_test_db()
    try:
        pr_service = PullRequestService(db)
        dispatcher = Mock()
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
        db.close()


def test_flaky_test_workflow_enqueues_job_and_dispatches_task() -> None:
    db = make_test_db()
    try:
        flaky_service = FlakyTestService(db)
        dispatcher = Mock()
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
        db.close()


def test_pull_request_workflow_marks_dispatch_failed_when_dispatcher_raises() -> None:
    db = make_test_db()
    try:
        pr_service = PullRequestService(db)
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

        stored = db.query(PullRequestRecord).one()
        assert stored.status == "dispatch_failed"
    finally:
        db.close()


def test_flaky_test_workflow_marks_dispatch_failed_when_dispatcher_raises() -> None:
    db = make_test_db()
    try:
        flaky_service = FlakyTestService(db)
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

        stored = db.query(FlakyTestRun).one()
        assert stored.status == "dispatch_failed"
    finally:
        db.close()


def test_github_webhook_workflow_reuses_existing_record_for_same_delivery_id() -> None:
    db = make_test_db()
    try:
        pr_service = PullRequestService(db)
        dispatcher = Mock()
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
        assert db.query(PullRequestRecord).count() == 1
        dispatcher.dispatch_pull_request_analysis.assert_called_once_with(first.id)
    finally:
        db.close()
