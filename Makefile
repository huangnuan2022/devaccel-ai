install:
	pip install -e ".[dev]"

migrate:
	alembic upgrade head

run-api:
	uvicorn app.main:app --reload

run-worker:
	celery -A app.workers.celery_app worker --loglevel=info

test:
	pytest

lint:
	ruff check .
