from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "新保研在线判题 API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "development-only-change-me-32-characters"
    judge_result_secret: str = "development-judge-result-secret"
    database_url: str = "sqlite:///./data/dev.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_result_backend: str = "redis://127.0.0.1:6379/2"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    refresh_cookie_name: str = "oj_refresh"
    refresh_cookie_secure: bool = False
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    storage_root: Path = Path("./data")
    source_code_max_bytes: int = 65_536
    test_data_max_compressed_bytes: int = 52_428_800
    test_data_max_uncompressed_bytes: int = 268_435_456
    test_data_max_files: int = 202
    submission_rate_limit: int = Field(default=8, ge=1)
    submission_rate_window_seconds: int = Field(default=60, ge=1)
    max_queued_submissions_per_user: int = Field(default=3, ge=1)
    judge_task_lease_seconds: int = Field(default=120, ge=10)
    judge_task_queue_timeout_seconds: int = Field(default=600, ge=30)
    judge_task_max_attempts: int = Field(default=3, ge=1)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from: str = "noreply@example.com"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.is_production:
            if len(self.secret_key) < 32 or self.secret_key.startswith("development-"):
                raise ValueError("生产环境必须配置独立的高强度 SECRET_KEY")
            if len(self.judge_result_secret) < 32 or self.judge_result_secret == self.secret_key:
                raise ValueError("生产环境必须配置独立的高强度 JUDGE_RESULT_SECRET")
            if not self.refresh_cookie_secure:
                raise ValueError("生产环境必须启用 REFRESH_COOKIE_SECURE")
            if "*" in self.cors_origin_list:
                raise ValueError("生产环境不允许不受控的 CORS 通配符")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
