import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="chessamy-pytest-")

import pytest  # noqa: E402

import app as app_module  # noqa: E402


@pytest.fixture(scope="session")
def app():
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture()
def client(app):
    return app.test_client()


def unique_name(prefix="user"):
    return prefix + uuid.uuid4().hex[:8]


@pytest.fixture()
def user(client):
    username = unique_name()
    response = client.post(
        "/api/register",
        json={"username": username, "password": "pass1234"},
    )
    data = response.get_json()
    assert data["ok"], data
    client.post("/api/coach/select", json={"coach_id": 1})
    data["username"] = username
    return data
