"""Shared fixtures: a fresh seeded SQLite database per test."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402


@pytest.fixture()
def app():
    tmp = tempfile.mkdtemp()

    class TestConfig(Config):
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(tmp, "test.db")
        UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        TESTING = True

    app = create_app(TestConfig)
    with app.app_context():
        from seed import seed
        seed()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()
