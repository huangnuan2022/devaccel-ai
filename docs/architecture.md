# DevAccel-AI Architecture

## 1. System Layers

This project is organized into five layers commonly used in production backend systems:

1. Interface Layer
   - FastAPI HTTP APIs
   - GitHub webhook entrypoint
2. Application Layer
   - PR analysis orchestration
   - Flaky triage orchestration
3. Domain Layer
   - Core entities such as pull requests, analyses, failures, and clusters
4. Infrastructure Layer
   - PostgreSQL
   - Redis
   - Celery
   - OpenAI / Bedrock
   - DynamoDB
5. Delivery Layer
   - Docker
   - GitHub Actions
   - ECS / Lambda / Step Functions

## 2. Core Flows

### PR Copilot

```text
GitHub Webhook
  -> FastAPI receives a PR event
  -> Persist PR metadata to PostgreSQL
  -> Enqueue an analysis task in Celery / SQS
  -> LLM generates summary, risks, and suggested tests
  -> Persist analysis result
  -> Post back to GitHub comments or checks
```

### AWS Step Functions Target Shape

The local MVP still runs with Celery by default, but the async dispatch boundary now supports
two cloud-oriented paths:

1. `ASYNC_DISPATCH_BACKEND=step_functions`
   - FastAPI starts a Step Functions execution directly.
2. `ASYNC_DISPATCH_BACKEND=sqs_step_functions`
   - FastAPI sends a start-execution message to SQS.
   - A lightweight Lambda consumer can read that message and start the corresponding state machine.

The shared execution input contract is:

```json
{
  "workflow_name": "pull_request_analysis",
  "resource_type": "pull_request",
  "resource_id": 42,
  "trace_context": {
    "request_id": "req-123",
    "delivery_id": "delivery-123"
  }
}
```

State machine blueprints live in:

- `infra/step-functions/pull-request-analysis.asl.json`
- `infra/step-functions/flaky-test-triage.asl.json`

### Flaky-Test Triage

```text
CI / GitHub Actions / Scheduler
  -> Upload failure logs
  -> FastAPI creates a triage job
  -> Worker clusters related failures
  -> Retrieve historical patterns
  -> LLM generates likely root causes and fixes
  -> Persist triage results and state
```

## 3. Storage Responsibilities

- PostgreSQL
  - Primary business tables
  - Audit records
  - API query source
- Redis
  - Celery broker and result backend
  - Hot-path cache
  - Deduplication locks
- DynamoDB
  - High-volume CI artifact index
  - Prompt and rule cache
  - Fast lookup for historical flaky patterns

## 4. Recommended Development Order

Recommended order for implementation:

1. Define the architecture and API contracts
2. Define the database models
3. Get the synchronous workflow working first
4. Add Celery / SQS for asynchronous execution
5. Integrate GitHub, OpenAI, and AWS last

## 5. Why This Structure

- The project keeps HTTP handling, orchestration, domain logic, and infrastructure concerns separated
- This reduces coupling across API handlers, worker execution, and provider integrations
- It lowers the cost of testing, replacing external providers, and evolving deployment targets over time
