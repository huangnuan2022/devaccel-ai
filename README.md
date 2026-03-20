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

### 2. Start local dependencies

```bash
docker compose up -d postgres redis
```

### 3. Start the API

```bash
uvicorn app.main:app --reload
```

### 4. Start the worker

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

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
    "failure_log": "TimeoutError: operation exceeded 30 seconds"
  }'
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
- Automated tests across API, service, and task layers

Planned next steps:

- Replace the temporary token-based GitHub API access path with installation-token flow
- Replace mock LLM responses with real OpenAI / Bedrock integrations
- Add Alembic migrations for schema evolution
- Expand observability, retry handling, and deployment automation
