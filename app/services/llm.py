from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.services.exceptions import LLMProviderConfigurationError
from app.services.llm_prompts import LLMPromptBuilder, PromptSet

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
        risks = "Potential regression around error handling, database writes, and edge-case retries."
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
            "Likely timing-sensitive assertion or shared mutable fixture causing non-deterministic state."
        )
        suggested_fix = (
            "Isolate shared fixtures, freeze time-dependent assertions, and add deterministic retries "
            "only after root cause is confirmed."
        )
        if "timeout" in failure_log.lower():
            suspected_root_cause = "Likely environment-dependent timeout under concurrent CI load."
            suggested_fix = "Raise explicit wait condition, remove sleep-based checks, and instrument retries."
        return FlakyTriageResult(
            cluster_key=cluster_key,
            suspected_root_cause=suspected_root_cause,
            suggested_fix=suggested_fix,
        )


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
        self.provider = provider or self._build_provider(provider_name or self.settings.llm_provider)

    @property
    def provider_name(self) -> str:
        return self.provider.provider_name

    def analyze_pull_request(self, diff_text: str, title: str) -> LLMAnalysisResult:
        prompt = self.prompt_builder.build_pull_request_analysis_prompt(diff_text, title)
        return self.provider.analyze_pull_request(prompt, diff_text=diff_text, title=title)

    def triage_flaky_test(self, test_name: str, failure_log: str) -> FlakyTriageResult:
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
        if normalized in {"openai", "bedrock"}:
            raise LLMProviderConfigurationError(
                f"LLM provider '{normalized}' is not wired yet. Keep llm_provider=mock until the real "
                "provider integration is implemented."
            )
        raise LLMProviderConfigurationError(f"Unsupported llm_provider: {provider_name}")
