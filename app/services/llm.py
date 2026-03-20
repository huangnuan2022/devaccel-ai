from dataclasses import dataclass


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


class LLMClient:
    """Mockable LLM adapter.

    Start with stable mock responses, then replace them with real OpenAI or Bedrock calls.
    """

    def analyze_pull_request(self, diff_text: str, title: str) -> LLMAnalysisResult:
        summary = f"PR '{title}' changes {max(1, len(diff_text.splitlines()))} diff lines."
        risks = "Potential regression around error handling, database writes, and edge-case retries."
        suggested_tests = (
            "1. Add success-path regression test.\n"
            "2. Add failure-path test for invalid inputs.\n"
            "3. Add integration test covering retry/idempotency behavior."
        )
        return LLMAnalysisResult(summary=summary, risks=risks, suggested_tests=suggested_tests)

    def triage_flaky_test(self, test_name: str, failure_log: str) -> FlakyTriageResult:
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
