"""Shared test fixtures for Lernmanager."""
import pytest
import config
import models
from app import app as flask_app


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
