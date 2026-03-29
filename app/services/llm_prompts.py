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
                "meaningful engineering risks, and suggest practical tests. Follow the structured "
                "response schema exactly."
            ),
            user_prompt=(
                f"Pull request title:\n{title}\n\n"
                "Unified diff or patch content:\n"
                f"{diff_text}\n\n"
                "Return concise analysis covering summary, risks, and suggested tests."
            ),
        )

    def build_flaky_test_triage_prompt(self, test_name: str, failure_log: str) -> PromptSet:
        return PromptSet(
            system_prompt=(
                "You are a CI reliability assistant. Group flaky failures, infer likely root causes, "
                "and recommend the next debugging or stabilization step. Follow the structured "
                "response schema exactly. The cluster_key must be a short stable snake_case category "
                "name with 2 to 5 tokens, no spaces, and no 'cluster:' prefix. Prefer durable failure "
                "families such as timeout_under_ci_load, shared_fixture_state_leak, async_retry_race, "
                "order_dependent_test_state, or external_dependency_instability. Do not return prose, "
                "sentences, or a raw test name unless the failure pattern truly has no better category."
            ),
            user_prompt=(
                f"Test name:\n{test_name}\n\n"
                "Failure log:\n"
                f"{failure_log}\n\n"
                "Return concise triage covering cluster key, suspected root cause, and suggested fix. "
                "Use a cluster_key that can be reused across similar failures in future runs."
            ),
        )
