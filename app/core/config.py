from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DevAccel-AI"
    app_env: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./devaccel.db"
    test_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    async_dispatch_backend: str = "celery"

    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    aws_region: str = "us-east-1"

    github_app_id: str = ""
    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2022-11-28"
    github_webhook_secret: str = ""
    github_private_key_path: str = ""
    flaky_triage_ingest_token: str = ""

    dynamodb_table: str = "devaccel-artifacts"
    sqs_queue_url: str = ""
    step_functions_state_machine_arn: str = ""
    cloudwatch_log_group: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
