from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import Base, get_db
from app.main import create_app
from app.models import User, UserRole, UserStatus
from app.services.rate_limit import rate_limiter


@pytest.fixture
def db_session(tmp_path) -> Generator[Session, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api-test.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session: Session, tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    TestingSession = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    settings = get_settings()
    original_storage = settings.storage_root
    settings.storage_root = tmp_path / "storage"
    settings.storage_root.mkdir(parents=True)
    rate_limiter._local.clear()
    try:
        import redis as _redis

        client_redis = _redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)
        for pattern in ("login:*", "forgot:*", "submission:*", "password-reset:*", "reset-email:*"):
            for key in client_redis.keys(pattern):
                client_redis.delete(key)
    except Exception:
        pass

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.tasks.results.SessionLocal", TestingSession)
    monkeypatch.setattr("app.tasks.dispatcher.dispatch_outbox", lambda task_id: True)
    with TestClient(app) as test_client:
        yield test_client
    settings.storage_root = original_storage


@pytest.fixture
def admin_user(db_session: Session) -> User:
    user = User(
        username="admin",
        nickname="管理员",
        email="admin@example.com",
        password_hash=hash_password("Admin12345"),
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_headers(client: TestClient, admin_user: User) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"account": "admin", "password": "Admin12345"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "student", "nickname": "学生", "email": "student@example.com", "password": "Student123"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}
