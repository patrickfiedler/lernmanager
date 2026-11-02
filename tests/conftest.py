"""Shared test fixtures for Lernmanager."""
import pytest
import config
import models
from app import app as flask_app
from werkzeug.security import generate_password_hash


@pytest.fixture(autouse=True)
def _no_real_service_and_cheap_hash(request, monkeypatch):
    """Every test starts without a grading service: several set the URL directly,
    and without this reset it leaked into later tests, which then waited on the
    real host. monkeypatch restores both values after the test, however they were set.

    The real password hash costs 0.11 s and fixtures create accounts in nearly
    every test. test_password_hash.py checks the real one (marker real_hash)."""
    monkeypatch.setattr(config, 'GRADING_SERVICE_URL', '')
    monkeypatch.setattr(config, 'GRADING_SERVICE_TOKEN', '')
    if not request.node.get_closest_marker('real_hash'):
        monkeypatch.setattr(models, 'generate_password_hash',
                            lambda password: generate_password_hash(password, method='pbkdf2:sha256:1'))


@pytest.fixture
def db(tmp_path):
    """Isolated SQLite database for model-layer tests. No Flask needed."""
    config.DATABASE = str(tmp_path / "test.db")
    config.LLM_ENABLED = False
    models.init_db()


@pytest.fixture
def app(tmp_path):
    """Flask test app with isolated database for route tests."""
    config.DATABASE = str(tmp_path / "test.db")
    config.LLM_ENABLED = False
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    models.init_db()
    # id 1 on a fresh DB: several tests set sess["admin_id"] = 1 directly, and
    # permissions.py looks the account up on every request.
    models.create_admin("admin", "testpass")
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def as_admin(client):
    """HTTP client with an active admin session."""
    models.create_admin("testadmin", "testpass")
    with models.db_session() as conn:
        admin = conn.execute("SELECT id FROM admin WHERE username = 'testadmin'").fetchone()
    with client.session_transaction() as sess:
        sess["admin_id"] = admin["id"]
    return client
