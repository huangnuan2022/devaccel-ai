import logging
import time
from dataclasses import dataclass
from typing import Protocol, cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.exceptions import LLMProviderConfigurationError, LLMProviderInvocationError
from app.services.llm_prompts import LLMPromptBuilder, PromptSet

logger = logging.getLogger(__name__)


@dataclass
class LLMAnalysisResult:
    summary: str
    risks: str
    suggested_tests: str


@dataclass
class FlakyTriageResult:
    cluster_key: str
    suspected_root_cause: str
    suggested_fix: str


class _PullRequestAnalysisPayload(BaseModel):
    summary: str
    risks: str
    suggested_tests: str


class _FlakyTriagePayload(BaseModel):
    cluster_key: str
    suspected_root_cause: str
    suggested_fix: str


class LLMProvider(Protocol):
    provider_name: str

    def analyze_pull_request(
        self, prompt: PromptSet, *, diff_text: str, title: str
    ) -> LLMAnalysisResult: ...

    def triage_flaky_test(
        self, prompt: PromptSet, *, test_name: str, failure_log: str
    ) -> FlakyTriageResult: ...


class MockLLMProvider:
    provider_name = "mock"

    def analyze_pull_request(
        self, prompt: PromptSet, *, diff_text: str, title: str
    ) -> LLMAnalysisResult:
        del prompt
        summary = f"PR '{title}' changes {max(1, len(diff_text.splitlines()))} diff lines."
        risks = (
            "Potential regression around error handling, database writes, and edge-case retries."
        )
        suggested_tests = (
            "1. Add success-path regression test.\n"
            "2. Add failure-path test for invalid inputs.\n"
            "3. Add integration test covering retry/idempotency behavior."
        )
        return LLMAnalysisResult(summary=summary, risks=risks, suggested_tests=suggested_tests)

    def triage_flaky_test(
        self, prompt: PromptSet, *, test_name: str, failure_log: str
    ) -> FlakyTriageResult:
        del prompt
        normalized = test_name.lower().replace("::", ".").replace(" ", "-")
        cluster_key = f"cluster:{normalized}"
        suspected_root_cause = (
            "Likely timing-sensitive assertion or shared mutable fixture causing "
            "non-deterministic state."
        )
        suggested_fix = (
            "Isolate shared fixtures, freeze time-dependent assertions, and add "
            "deterministic retries only after root cause is confirmed."
        )
        if "timeout" in failure_log.lower():
            suspected_root_cause = "Likely environment-dependent timeout under concurrent CI load."
            suggested_fix = (
                "Raise explicit wait condition, remove sleep-based checks, and instrument retries."
            )
        return FlakyTriageResult(
            cluster_key=cluster_key,
            suspected_root_cause=suspected_root_cause,
            suggested_fix=suggested_fix,
        )


class OpenAILLMProvider:
    provider_name = "openai"

    def __init__(self, client: OpenAI | None = None, model: str | None = None) -> None:
        self.settings = get_settings()
        self.model = model or self.settings.openai_model
        if client is not None:
            self.client = client
            return
        if not self.settings.openai_api_key:
            raise LLMProviderConfigurationError(
                "OpenAI provider requires openai_api_key before llm_provider=openai can be used"
            )
        self.client = OpenAI(api_key=self.settings.openai_api_key)

    def analyze_pull_request(
        self, prompt: PromptSet, *, diff_text: str, title: str
    ) -> LLMAnalysisResult:
        del diff_text, title
        started_at = time.perf_counter()
        try:
            payload = cast(
                _PullRequestAnalysisPayload,
                self._generate_structured_output(prompt, _PullRequestAnalysisPayload),
            )
            result = LLMAnalysisResult(
                summary=payload.summary,
                risks=payload.risks,
                suggested_tests=payload.suggested_tests,
            )
        except LLMProviderInvocationError:
            logger.warning(
                "OpenAI pull request analysis failed model=%s elapsed_ms=%d",
                self.model,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise

        logger.info(
            "OpenAI pull request analysis completed model=%s elapsed_ms=%d",
            self.model,
            int((time.perf_counter() - started_at) * 1000),
        )
        return result

    def triage_flaky_test(
        self, prompt: PromptSet, *, test_name: str, failure_log: str
    ) -> FlakyTriageResult:
        del test_name, failure_log
        started_at = time.perf_counter()
        try:
            payload = cast(
                _FlakyTriagePayload,
                self._generate_structured_output(prompt, _FlakyTriagePayload),
            )
            result = FlakyTriageResult(
                cluster_key=payload.cluster_key,
                suspected_root_cause=payload.suspected_root_cause,
                suggested_fix=payload.suggested_fix,
            )
        except LLMProviderInvocationError:
            logger.warning(
                "OpenAI flaky triage failed model=%s elapsed_ms=%d",
                self.model,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise

        logger.info(
            "OpenAI flaky triage completed model=%s elapsed_ms=%d",
            self.model,
            int((time.perf_counter() - started_at) * 1000),
        )
        return result

    def _generate_structured_output(
        self,
        prompt: PromptSet,
        text_format: type[_PullRequestAnalysisPayload] | type[_FlakyTriagePayload],
    ) -> _PullRequestAnalysisPayload | _FlakyTriagePayload:
        try:
            response = self.client.responses.parse(
                model=self.model,
                instructions=prompt.system_prompt,
                input=prompt.user_prompt,
                text_format=text_format,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise LLMProviderInvocationError(f"OpenAI request failed: {exc}") from exc

        payload = getattr(response, "output_parsed", None)
        if payload is None:
            raise LLMProviderInvocationError(
                "OpenAI structured output did not match the expected schema"
            )
        return payload


class LLMClient:
    """LLM application adapter.

    Prompt construction and provider selection live here so domain services can depend on a
    stable interface while provider-specific integrations evolve underneath.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        prompt_builder: LLMPromptBuilder | None = None,
        provider_name: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self.prompt_builder = prompt_builder or LLMPromptBuilder()
        self.provider = provider or self._build_provider(
            provider_name or self.settings.llm_provider
        )

    @property
    def provider_name(self) -> str:
        return self.provider.provider_name

    def analyze_pull_request(self, diff_text: str, title: str) -> LLMAnalysisResult:
        logger.info("LLM analyze_pull_request provider=%s", self.provider_name)
        prompt = self.prompt_builder.build_pull_request_analysis_prompt(diff_text, title)
        return self.provider.analyze_pull_request(prompt, diff_text=diff_text, title=title)

    def triage_flaky_test(self, test_name: str, failure_log: str) -> FlakyTriageResult:
        logger.info("LLM triage_flaky_test provider=%s", self.provider_name)
        prompt = self.prompt_builder.build_flaky_test_triage_prompt(test_name, failure_log)
        return self.provider.triage_flaky_test(
            prompt,
            test_name=test_name,
            failure_log=failure_log,
        )

    def _build_provider(self, provider_name: str) -> LLMProvider:
        normalized = provider_name.lower().strip()
        if normalized == "mock":
            return MockLLMProvider()
        if normalized == "openai":
            return OpenAILLMProvider()
        if normalized == "bedrock":
            raise LLMProviderConfigurationError(
                "LLM provider 'bedrock' is not wired yet. Keep llm_provider=mock "
                "or openai until the Bedrock integration is implemented."
            )
        raise LLMProviderConfigurationError(f"Unsupported llm_provider: {provider_name}")
