import pytest

from app.core.config import Settings


def test_production_rejects_development_secrets():
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            secret_key="development-only-change-me-32-characters",
            refresh_cookie_secure=True,
        )


def test_production_requires_secure_cookie_and_independent_secrets():
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            secret_key="a" * 40,
            judge_result_secret="b" * 40,
            refresh_cookie_secure=False,
        )
    settings = Settings(
        app_env="production",
        secret_key="a" * 40,
        judge_result_secret="b" * 40,
        refresh_cookie_secure=True,
    )
    assert settings.is_production
