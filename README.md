# DevAccel-AI

DevAccel-AI is a backend platform for two engineering workflows:

- PR Copilot: ingest pull request events, assemble review context, generate summaries and risk signals, and persist analysis output
- Flaky-Test Triage: ingest CI failures, cluster related flakes, propose likely root causes, and persist triage results

The repository currently contains a runnable MVP with clean layering for API, workflow orchestration, background jobs, persistence, and external integration points.

## Core Capabilities

- FastAPI HTTP APIs for PR analysis, flaky-test triage, and GitHub webhook ingestion
- Celery-based background execution with Redis as the broker
- PostgreSQL-backed persistence for PR and flaky-test records
- Workflow/application services that separate route handling from async dispatch
- Webhook hardening with signature validation, delivery-id idempotency, and explicit failure semantics
- Mockable LLM and GitHub integration layers so external providers can be swapped in later

## Architecture

High-level request flow:

```text
Client / GitHub Webhook
        |
        v
      FastAPI
        |
        v
  Workflow Services
   |            |
   v            v
Domain Services  Task Dispatcher
   |            |
   v            v
PostgreSQL     Celery / Redis
                  |
                  v
                Worker
                  |
                  v
         GitHub PR Content / LLM
```

Additional architecture details are documented in [docs/architecture.md](docs/architecture.md).

## Repository Layout

```text
app/
  api/          FastAPI routes and dependency wiring
  core/         configuration and logging
  db/           database engine and session management
  lambdas/      AWS Lambda handler entrypoints
  models/       SQLAlchemy ORM models
  schemas/      request and response models
  services/     domain services, workflows, GitHub adapters
  tasks/        Celery task entrypoints
  workers/      Celery app configuration
docs/           public architecture and roadmap documents
tests/          automated tests
.github/        CI workflow definitions
```

## Local Development

### 1. Prepare the environment

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

The current default is `LLM_PROVIDER=mock`, which keeps PR analysis and flaky triage deterministic while the real OpenAI / Bedrock integrations are prepared behind a provider boundary.

You can now switch the PR/flaky analysis path to OpenAI by setting:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

The OpenAI path now uses schema-constrained structured outputs via the Responses API instead of relying only on prompt-level JSON instructions.

The repository still defaults to `mock` until you explicitly opt into the real provider.

### 2. Start local dependencies

```bash
docker compose up -d postgres redis
```

### 3. Run database migrations

```bash
alembic upgrade head
```

If your local PostgreSQL schema predates Alembic adoption, apply the transitional SQL in `infra/sql/001_add_pull_request_github_columns.sql`, then mark the database as current:

```bash
psql "postgresql://devaccel:devaccel@localhost:5433/devaccel" -f infra/sql/001_add_pull_request_github_columns.sql
alembic stamp head
```

### 3.5 Prepare the test database

Database-backed tests now use PostgreSQL plus Alembic instead of SQLite `create_all(...)`.
Set `TEST_DATABASE_URL` to a dedicated test database and create it once before running pytest:

```bash
psql "postgresql://devaccel:devaccel@localhost:5433/postgres" -c "CREATE DATABASE devaccel_test"
.venv/bin/python -m pytest tests/ -vv
```

If `devaccel_test` already exists, PostgreSQL will report that and you can ignore it.
The test fixture now refuses to reset databases that:

- match `DATABASE_URL`
- do not end with `_test`
- point at a non-local host
### 4. Start the API

```bash
uvicorn app.main:app --reload
```

### 5. Start the worker

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

### Container-first startup path

If you want Docker Compose to enforce the migration-first order, start the full stack with:

```bash
docker compose up --build
```

This now runs a dedicated `migrate` service before the API and worker start. The compose path is:

1. `postgres` becomes healthy
2. `migrate` runs `alembic upgrade head`
3. `api` and `worker` start only after the migration step succeeds

That keeps the standard local container entrypoint aligned with the repository's migration-first rule.

## Example API Calls

### Create a PR analysis job

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pull-requests/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "repo_full_name": "acme/payments",
    "pr_number": 42,
    "title": "Refactor payment retry flow",
    "author": "alice",
    "diff_text": "+++ services/payment.py\n+ retry_count += 1"
  }'
```

### Fetch a PR analysis result

```bash
curl http://127.0.0.1:8000/api/v1/pull-requests/1
```

### Create a flaky-test triage job

```bash
curl -X POST http://127.0.0.1:8000/api/v1/flaky-tests/triage \
  -H "Content-Type: application/json" \
  -d '{
    "test_name": "test_retry_payment_timeout",
    "suite_name": "payments.integration",
    "branch_name": "main",
    "ci_provider": "github_actions",
    "workflow_name": "CI",
    "job_name": "pytest",
    "run_url": "https://github.com/acme/payments/actions/runs/123",
    "commit_sha": "abc123def456",
    "failure_log": "TimeoutError: operation exceeded 30 seconds"
  }'
```

This route is the current trigger point for flaky triage. In a realistic setup, your CI system
(for example GitHub Actions) would call this endpoint after a failed test job and pass along the
job metadata plus a trimmed failure log.

If you want to protect that ingress path, set `FLAKY_TRIAGE_INGEST_TOKEN` and have CI send:

```bash
Authorization: Bearer <your-token>
```

To keep the platform repository CI clean, the failure-forwarding logic now lives in a dedicated
integration example:

- [`examples/github-actions/flaky-triage-forwarder.yml`](examples/github-actions/flaky-triage-forwarder.yml)

This keeps [`.github/workflows/ci.yml`](.github/workflows/ci.yml) focused on this repository's own
lint/test checks, while the forwarder file shows how a user repository can POST failures into
DevAccel-AI.

For the cloud-oriented `sqs_step_functions` path, the repository now also includes a minimal
Lambda-side consumer skeleton:

- `app/lambdas/sqs_step_functions_handler.py`
- `app/services/sqs_step_functions_consumer.py`

That handler is intentionally narrow in scope:

1. read SQS records
2. validate each record body against `SqsStepFunctionsDispatchMessage`
3. call Step Functions `start_execution`

The forwarder sends the payload when:

- the test step fails
- `DEVACCEL_API_URL` is configured as a GitHub Actions secret
- `DEVACCEL_FLAKY_TRIAGE_TOKEN` is configured as a GitHub Actions secret

The forwarder trims the pytest output, derives the first failed test node when possible, and POSTs
a real triage payload to your API.

If you want to use it from another repository, copy the file or convert it into a reusable workflow.
Its core behavior is:

```yaml
- name: Send flaky triage payload
  if: failure()
  run: |
    curl -X POST "$DEVACCEL_API_URL/api/v1/flaky-tests/triage" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${{ secrets.DEVACCEL_FLAKY_TRIAGE_TOKEN }}" \
      -d @- <<'JSON'
    {
      "test_name": "test_retry_payment_timeout",
      "suite_name": "payments.integration",
      "branch_name": "${{ github.ref_name }}",
      "ci_provider": "github_actions",
      "workflow_name": "${{ github.workflow }}",
      "job_name": "${{ github.job }}",
      "run_url": "https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}",
      "commit_sha": "${{ github.sha }}",
      "failure_log": "Trimmed test failure output goes here"
    }
    JSON
```

### Simulate a GitHub webhook

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-GitHub-Delivery: delivery-123" \
  -d '{
    "action": "opened",
    "number": 42,
    "installation": {"id": 12345678},
    "repository": {"full_name": "acme/payments"},
    "pull_request": {
      "title": "Refactor payment retry flow",
      "user": {"login": "alice"}
    }
  }'
```

## Current Scope

Implemented in the current MVP:

- API endpoints for PR analysis, flaky-test triage, and webhook ingestion
- Async task dispatch with explicit queued/completed/dispatch_failed state handling
- Delivery-id deduplication for GitHub webhook ingestion
- Worker-side GitHub PR patch retrieval path using GitHub pull request files data
- Prompt-builder and provider boundary for LLM calls, with OpenAI wired as the first real provider option using structured outputs
- Flaky-test triage records now accept CI metadata such as provider, workflow, job, run URL, and commit SHA so CI systems can trigger richer triage jobs
- Flaky-test triage ingress can now be protected with an optional bearer token for CI-originated calls
- Background jobs now persist failure status and error_message when provider/content retrieval fails
- Provider/model/timing logs now cover LLM invocations plus key GitHub patch-fetch workflow steps
- Automated tests across API, service, and task layers using a dedicated PostgreSQL test database

Planned next steps:

- Harden installation-token refresh, observability, and failure handling for GitHub App access
- Add end-to-end validation and richer observability for the new OpenAI provider path
- Implement the Bedrock provider behind the same prompt/provider abstraction
- Expand observability, retry handling, and deployment automation
