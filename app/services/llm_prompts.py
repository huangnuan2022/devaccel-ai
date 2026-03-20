from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSet:
    system_prompt: str
    user_prompt: str


class LLMPromptBuilder:
    def build_pull_request_analysis_prompt(self, diff_text: str, title: str) -> PromptSet:
        return PromptSet(
            system_prompt=(
                "You are a senior code review copilot. Summarize pull request changes, highlight "
                "meaningful engineering risks, and suggest practical tests. Return valid JSON only "
                "with keys: summary, risks, suggested_tests."
            ),
            user_prompt=(
                f"Pull request title:\n{title}\n\n"
                "Unified diff or patch content:\n"
                f"{diff_text}\n\n"
                "Return concise analysis covering summary, risks, and suggested tests. "
                "The response must be a single JSON object."
            ),
        )

    def build_flaky_test_triage_prompt(self, test_name: str, failure_log: str) -> PromptSet:
        return PromptSet(
            system_prompt=(
                "You are a CI reliability assistant. Group flaky failures, infer likely root causes, "
                "and recommend the next debugging or stabilization step. Return valid JSON only "
                "with keys: cluster_key, suspected_root_cause, suggested_fix."
            ),
            user_prompt=(
                f"Test name:\n{test_name}\n\n"
                "Failure log:\n"
                f"{failure_log}\n\n"
                "Return concise triage covering cluster key, suspected root cause, and suggested fix. "
                "The response must be a single JSON object."
            ),
        )
