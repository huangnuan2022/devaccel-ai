# DevAccel-AI Development Roadmap

This document is written for beginners. Do not try to implement AWS, GitHub App integration, LLM providers, and async workflows all at once. Build the system in stages.

## Phase 0: Understand the Product

The goal is not just to add a few endpoints. You are building a full engineering system:

1. API service
2. Background job processing
3. Database
4. Cache
5. CI
6. Deployment entrypoints
7. External platform integrations

Typical production-oriented development looks like this:

1. Build the project scaffold
2. Get the data flow working end-to-end
3. Replace mocks with real integrations
4. Add reliability, observability, and scale

## Phase 1: Run the Local Development Environment

Your first goal is simple: make sure the API and worker can start locally.

Run these commands:

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
docker compose up -d postgres redis
uvicorn app.main:app --reload
```

For local host-based development, use these defaults from `.env`:

```text
DATABASE_URL=postgresql+psycopg://devaccel:devaccel@localhost:5433/devaccel
REDIS_URL=redis://localhost:6379/0
```

Then open a second terminal:

```bash
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

If both processes start successfully, this phase is complete.

## Phase 2: Understand the PR Copilot Loop

Focus on this workflow:

1. A client calls `POST /api/v1/pull-requests/analyze`
2. The API writes PR metadata to the database
3. The API dispatches a Celery task
4. The worker runs a mock LLM analysis
5. The database status becomes `completed`
6. You call `GET /api/v1/pull-requests/{id}` to inspect the result

The point of this phase is not model quality. It is:

- A complete business workflow
- A clear state transition model
- Durable persistence
- Retry-ready async execution

## Phase 3: Understand the Flaky-Test Triage Loop

This flow is similar:

1. Submit a failure log
2. Create a triage record
3. The worker computes a cluster key
4. The LLM produces likely causes and suggested fixes
5. Persist the triage result

Later you can replace the simple cluster key with a real clustering strategy, such as:

- Normalize stack traces with regex rules
- Remove timestamps and random IDs
- Retrieve similar failures with embeddings

## Phase 4: Replace Mocks with Real Integrations

Add external integrations in this order:

1. GitHub App webhook
2. OpenAI / Bedrock
3. DynamoDB
4. SQS / Lambda / Step Functions
5. CloudWatch and tracing

The reason is straightforward: the earlier you add external systems, the harder debugging becomes.

## Phase 5: Production Readiness Work

This is where a practice project becomes a production-style system. You need:

1. Configuration management
   - Never hardcode secrets
   - Inject settings through environment variables
2. Schema migrations
   - Do not rely on `create_all`
   - Use Alembic for versioned migrations
3. Logging and observability
   - Request logs
   - Async worker logs
   - Error alerting
4. Testing
   - Unit tests
   - API integration tests
   - Task execution tests
5. Release workflow
   - GitHub Actions
   - Container image build
   - Environment separation: dev / staging / prod

## What You Should Do Next

If you want to keep building this project, follow this order:

1. Run the current scaffold locally
2. Add a real GitHub webhook integration
3. Add real OpenAI / Bedrock calls
4. Add Alembic migrations and more tests
5. Build the AWS deployment layer
