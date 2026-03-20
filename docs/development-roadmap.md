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

## Phase 4: Data and Reliability

Goals:

1. Introduce Alembic migrations
2. Strengthen delivery and dispatch consistency
3. Add retry-safe async processing semantics
4. Expand auditability for webhook, PR, and triage state transitions

## Phase 5: Platform Expansion

Goals:

1. Add DynamoDB-backed artifact and rule storage
2. Expand queueing and fan-out patterns with SQS / Lambda / Step Functions
3. Improve flaky clustering and historical retrieval quality
4. Add GitHub Checks / comment write-back

## Phase 6: Production Readiness

Goals:

1. Improve structured logging, tracing, and metrics
2. Expand CI coverage for linting, typing, and test execution
3. Add environment-aware deployment automation
4. Harden operational playbooks and release workflows
