import json
from dataclasses import dataclass
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.core.config import get_settings
from app.services.exceptions import LLMProviderConfigurationError, LLMProviderInvocationError
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
        response_text = self._generate_text(prompt)
        payload = self._parse_json_object(response_text)
        return LLMAnalysisResult(
            summary=self._require_text_field(payload, "summary"),
            risks=self._require_text_field(payload, "risks"),
            suggested_tests=self._require_text_field(payload, "suggested_tests"),
        )

    def triage_flaky_test(
        self, prompt: PromptSet, *, test_name: str, failure_log: str
    ) -> FlakyTriageResult:
        del test_name, failure_log
        response_text = self._generate_text(prompt)
        payload = self._parse_json_object(response_text)
        return FlakyTriageResult(
            cluster_key=self._require_text_field(payload, "cluster_key"),
            suspected_root_cause=self._require_text_field(payload, "suspected_root_cause"),
            suggested_fix=self._require_text_field(payload, "suggested_fix"),
        )

    def _generate_text(self, prompt: PromptSet) -> str:
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=prompt.system_prompt,
                input=prompt.user_prompt,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise LLMProviderInvocationError(f"OpenAI request failed: {exc}") from exc

        output_text = getattr(response, "output_text", "")
        if not isinstance(output_text, str) or not output_text.strip():
            raise LLMProviderInvocationError("OpenAI response did not contain output_text")
        return output_text

    def _parse_json_object(self, response_text: str) -> dict[str, object]:
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise LLMProviderInvocationError("OpenAI response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LLMProviderInvocationError("OpenAI response JSON must be an object")
        return payload

    def _require_text_field(self, payload: dict[str, object], field_name: str) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise LLMProviderInvocationError(
                f"OpenAI response JSON must include non-empty string field '{field_name}'"
            )
        return value.strip()


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
        if normalized == "openai":
            return OpenAILLMProvider()
        if normalized == "bedrock":
            raise LLMProviderConfigurationError(
                "LLM provider 'bedrock' is not wired yet. Keep llm_provider=mock or openai until the "
                "Bedrock integration is implemented."
            )
        raise LLMProviderConfigurationError(f"Unsupported llm_provider: {provider_name}")
