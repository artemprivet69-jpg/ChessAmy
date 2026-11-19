import json
import uuid

import pytest


def unique_name(prefix="user"):
    return prefix + uuid.uuid4().hex[:8]


def test_register_returns_recovery_code(client):
    name = unique_name("reg")
    response = client.post("/api/register", json={"username": name, "password": "pass1234"})
    data = response.get_json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["user"]["username"] == name
    assert data["user"]["elo"] == 500
    assert data["recovery_code"].startswith("AMY-")


def test_register_duplicate_username(client):
    name = unique_name("dup")
    assert client.post("/api/register", json={"username": name, "password": "pass1234"}).status_code == 200
    response = client.post("/api/register", json={"username": name.upper(), "password": "pass1234"})
    assert response.status_code == 400
    assert "занят" in response.get_json()["error"]


@pytest.mark.parametrize(
    "password,message",
    [
        ("abc", "от 4 до 20"),
        ("abcdefgh", "цифру"),
        ("12345678", "букву"),
        ("pass 1234", "допустимы"),
    ],
)
def test_password_validation(client, password, message):
    response = client.post(
        "/api/register",
        json={"username": unique_name("pw"), "password": password},
    )
    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_recovery_flow(client):
    name = unique_name("rec")
    code = client.post(
        "/api/register", json={"username": name, "password": "pass1234"}
    ).get_json()["recovery_code"]
    client.post("/api/logout")

    bad = client.post(
        "/api/password/recover",
        json={"username": name, "code": "AMY-0000-0000-0000", "new_password": "newpass123"},
    )
    assert bad.status_code == 400

    good = client.post(
        "/api/password/recover",
        json={
            "username": name.lower(),
            "code": code.lower().replace("-", " "),
            "new_password": "newpass123",
        },
    )
    data = good.get_json()
    assert data["ok"] is True
    assert data["recovery_code"] != code
    client.post("/api/logout")
    assert client.post(
        "/api/login", json={"username": name, "password": "newpass123"}
    ).get_json()["ok"] is True


def test_change_password(client, user):
    bad = client.post(
        "/api/password/change",
        json={"current_password": "wrong1234", "new_password": "other1234"},
    )
    assert bad.status_code == 400
    good = client.post(
        "/api/password/change",
        json={"current_password": "pass1234", "new_password": "other1234"},
    )
    assert good.get_json()["ok"] is True
    client.post("/api/logout")
    assert client.post(
        "/api/login", json={"username": user["username"], "password": "other1234"}
    ).get_json()["ok"] is True


def test_export_and_import_account(client, user, app_module=None):
    import app as A

    uid = user["user"]["id"]
    with A.closing(A.get_db()) as db:
        db.execute(
            """INSERT INTO games (user_id, mode, bot_name, bot_elo, user_color, time_control,
            pgn, moves, result, reason, timed, status, created_at, finished_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                uid, "games", "Bot X", 1000, "white", "300+0", "1. e4 e5", "[]",
                "win", "checkmate", 1, "finished", "2026-01-01T00:00:00",
                "2026-01-01T00:05:00",
            ),
        )
        db.commit()

    export = client.get("/api/account/export")
    assert export.status_code == 200
    assert "attachment" in export.headers["Content-Disposition"]
    payload = json.loads(export.data.decode("utf-8"))
    assert payload["profile"]["username"] == user["username"]
    assert len(payload["games"]) == 1

    client.post("/api/logout")
    new_name = unique_name("copy")
    imported = client.post(
        "/api/account/import",
        json={"payload": payload, "username": new_name, "password": "pass1234"},
    )
    data = imported.get_json()
    assert data["ok"] is True
    assert data["imported"]["games"] == 1
    profile = client.get("/api/profile").get_json()
    assert profile["user"]["username"] == new_name
    assert profile["stats"]["total"] == 1
