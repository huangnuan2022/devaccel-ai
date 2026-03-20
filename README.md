# DevAccel-AI

DevAccel-AI is an intelligent engineering platform for GitHub pull request review and flaky-test triage. This repository provides an MVP scaffold that is beginner-friendly while following common large-scale backend engineering practices.

## 1. Product Goals

This project has two primary workflows:

1. PR Copilot
   - Receive GitHub PR events
   - Fetch diff and contextual metadata
   - Use an LLM to generate summaries, risk signals, and suggested test cases
   - Persist analysis results for audit and analytics
2. Flaky-Test Triage
   - Ingest CI failure samples
   - Cluster related failures
   - Propose fixes based on historical logs and prompt templates
   - Produce traceable triage records

## 2. Tech Stack

- API: FastAPI
- Async jobs: Celery + Redis
- Primary database: PostgreSQL
- Cache: Redis
- Artifact and rule cache: DynamoDB
- LLM providers: OpenAI / AWS Bedrock
- Deployment: Docker, ECS Fargate
- Event processing: GitHub Actions, SQS, Lambda, Step Functions

## 3. Project Structure

```text
app/
  api/          # FastAPI routes
  core/         # config and logging
  db/           # database engine and sessions
  models/       # SQLAlchemy models
  schemas/      # request and response schemas
  services/     # business services
  tasks/        # Celery tasks
  workers/      # worker configuration
docs/           # public architecture and setup docs
tests/          # automated tests
.github/        # CI workflows
```

## 4. Local Startup

### Step 1: Prepare the environment

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

### Step 2: Start dependencies

```bash
docker compose up -d postgres redis
```

If you run the API and Celery worker directly on your host machine, the default local endpoints are:

```text
PostgreSQL: localhost:5433
Redis: localhost:6379
```

### Step 3: Start the API

```bash
uvicorn app.main:app --reload
```

### Step 4: Start the Celery worker

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

## 4.1 API Examples

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
  -d '{
    "action": "opened",
    "repository": {"full_name": "acme/payments"},
    "pull_request": {
      "number": 42,
      "title": "Refactor payment retry flow",
      "body": "This PR improves retry logic.",
      "user": {"login": "alice"}
    }
  }'
```

## 5. Recommended Learning Order

If you are new to backend development, follow this order:

1. Read [docs/architecture.md](/Users/huangnuan/Downloads/DevAccel-AI/docs/architecture.md)
2. Read [app/main.py](/Users/huangnuan/Downloads/DevAccel-AI/app/main.py)
3. Review the API routes and schemas
4. Review how the service layer organizes business logic
5. Read the Celery tasks and deployment files

## 6. Suggested Next Steps

This repository currently implements a runnable MVP scaffold. Good next steps are:

- Integrate real GitHub App webhook verification
- Integrate real OpenAI / Bedrock calls
- Use Alembic for schema migrations
- Add DynamoDB reads and writes
- Post results back to GitHub Checks or comments
- Implement a stronger flaky clustering and similarity retrieval pipeline
