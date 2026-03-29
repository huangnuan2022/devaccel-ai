# DevAccel-AI Development Roadmap

This roadmap tracks the engineering path from the current MVP toward a production-style PR Copilot and flaky-test triage platform.

## Phase 1: Local MVP

Goals:

1. Run the API and worker locally
2. Persist core PR and flaky-test entities
3. Validate end-to-end async workflows
4. Establish baseline API, service, and task tests

Current status:

- Implemented

## Phase 2: GitHub Integration Hardening

Goals:

1. Keep webhook handling lightweight and idempotent
2. Move code-analysis input assembly to worker-side GitHub API fetches
3. Replace placeholder PR content with real files/patch retrieval
4. Evolve token handling toward GitHub App installation-token flow

Current status:

- In progress

## Phase 3: Real LLM Integration

Goals:

1. Replace mock PR analysis responses with real provider calls
2. Replace mock flaky-test triage responses with real provider calls
3. Centralize prompt construction and provider configuration
4. Add model/provider observability and failure handling

Current note:

- Prompt construction and provider selection are now separated from domain services.
- OpenAI is now wired as the first real provider path behind the shared `LLMClient`, with schema-constrained structured outputs.
- Background jobs now persist `failed` state plus `error_message` when provider calls fail.
- Minimal provider/content-fetch observability is now in place with provider/model/timing and job-state logs.
- Flaky-test triage now accepts optional CI metadata fields (`ci_provider`, `workflow_name`, `job_name`, `run_url`, `commit_sha`) so CI systems can trigger richer triage jobs without waiting for deeper CI log ingestion.
- Flaky-test triage ingress can now be protected with an optional bearer token, which is the first step toward safer CI-to-API triggering.
- Bedrock remains a follow-up provider on the same abstraction.

## Phase 4: Data and Reliability

Goals:

1. Introduce Alembic migrations
2. Strengthen delivery and dispatch consistency
3. Add retry-safe async processing semantics
4. Expand auditability for webhook, PR, and triage state transitions

Current note:

- Alembic is now initialized in the repository.
- The transitional SQL in `infra/sql/001_add_pull_request_github_columns.sql` remains only for pre-Alembic local databases that need to be aligned before `alembic stamp head`.
- Local container startup now includes a dedicated migration step before API and worker startup.
- Test database setup still uses `Base.metadata.create_all(...)`; aligning tests with migrations is an explicit follow-up item.

## Phase 5: Platform Expansion

Goals:

1. Add DynamoDB-backed artifact and rule storage
2. Expand queueing and fan-out patterns with SQS / Lambda / Step Functions
3. Improve flaky clustering and historical retrieval quality
4. Add GitHub Checks / comment write-back

Current note:

- Workflow services now depend on a generic async dispatch boundary instead of only a Celery-specific return shape.
- The current `TaskDispatcher` is explicitly the Celery adapter for that boundary, which keeps the local MVP intact while making the next SQS / Step Functions adapter additive instead of disruptive.

## Phase 6: Production Readiness

Goals:

1. Improve structured logging, tracing, and metrics
2. Expand CI coverage for linting, typing, and test execution
3. Add environment-aware deployment automation
4. Harden operational playbooks and release workflows
