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

- Beginners often mix API code, business logic, and SDK calls in one place
- This structure keeps responsibilities clear
- It lowers the cost of testing, swapping model providers, and changing deployment targets later
