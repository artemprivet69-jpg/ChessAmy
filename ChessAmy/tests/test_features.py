import time

import pytest


def test_settings_defaults_and_update(client, user):
    data = client.get("/api/settings").get_json()
    assert data["settings"]["bot_delay"] == 3
    assert data["settings"]["theme"] == "light"
    assert data["settings"]["sound"] is True

    updated = client.post(
        "/api/settings",
        json={"bot_delay": 1.5, "theme": "dark", "sound": False, "coordinates": False},
    ).get_json()
    assert updated["settings"]["bot_delay"] == 1.5
    assert updated["settings"]["theme"] == "dark"
    assert updated["settings"]["sound"] is False
    assert updated["settings"]["coordinates"] is False

    assert client.post("/api/settings", json={"theme": "neon"}).status_code == 400
    clamped = client.post("/api/settings", json={"bot_delay": 99}).get_json()
    assert clamped["settings"]["bot_delay"] == 5


def test_settings_applied_to_html(client, user):
    client.post("/api/settings", json={"theme": "dark", "coordinates": False})
    page = client.get("/profile").data.decode("utf-8")
    assert 'data-theme="dark"' in page
    assert 'data-coords="off"' in page


def test_backups_create_and_restore(client, user):
    created = client.post("/api/backups/create").get_json()
    assert created["ok"] is True
    name = created["name"]
    assert any(item["name"] == name for item in created["backups"])

    restored = client.post("/api/backups/restore", json={"name": name}).get_json()
    assert restored["ok"] is True

    bad = client.post("/api/backups/restore", json={"name": "../../database.db"})
    assert bad.status_code == 400


def test_backups_page_renders(client, user):
    page = client.get("/backups")
    assert page.status_code == 200
    assert "Резервные копии" in page.data.decode("utf-8")


def test_pages_smoke(client, user):
    for path in ("/menu", "/profile", "/import", "/training", "/backups"):
        assert client.get(path).status_code == 200, path


def test_async_bot_move(client, user):
    client.post("/api/settings", json={"bot_delay": 1})
    game = client.post(
        "/api/game/start",
        json={"mode": "games", "bot_elo": 1, "time_control": "1+0", "color": "white"},
    ).get_json()
    gid = game["game_id"]

    started = time.time()
    moved = client.post(
        "/api/game/move", json={"game_id": gid, "from": "e2", "to": "e4"}
    ).get_json()
    elapsed = time.time() - started

    assert moved["ok"] is True
    assert moved["state"]["thinking"] is True
    assert len(moved["state"]["moves"]) == 1
    assert elapsed < 1.5

    state = moved["state"]
    deadline = time.time() + 8
    while time.time() < deadline:
        state = client.get(f"/api/game/{gid}/state").get_json()["state"]
        if len(state["moves"]) >= 2 and not state["thinking"]:
            break
        time.sleep(0.15)
    assert len(state["moves"]) >= 2
    assert state["thinking"] is False


def test_fen_game_and_pgn_export(client, user):
    fen = "4k3/8/8/8/8/8/8/4K2R w K - 0 1"
    start = client.post(
        "/api/game/start",
        json={"mode": "games", "bot_elo": 1, "time_control": "1+0", "fen": fen},
    ).get_json()
    gid = start["game_id"]
    state = client.get(f"/api/game/{gid}/state").get_json()["state"]
    assert state["fen"] == fen

    client.post("/api/game/move", json={"game_id": gid, "from": "e1", "to": "e2"})
    client.post("/api/game/resign", json={"game_id": gid})
    pgn = client.get(f"/api/game/{gid}/export/pgn")
    assert pgn.status_code == 200
    text = pgn.data.decode("utf-8")
    assert '[SetUp "1"]' in text
    assert '[FEN "' in text


@pytest.mark.slow
def test_pgn_import_analysis_and_training(client, user):
    pgn = (
        '[White "Pytest"]\n[Black "Bot"]\n[Result "1-0"]\n\n'
        "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n"
    )
    imported = client.post("/api/import/pgn", json={"pgn": pgn}).get_json()
    assert imported["ok"] is True
    gid = imported["game_id"]

    analysis = client.get(f"/api/analysis/{gid}")
    assert analysis.status_code == 200

    training = client.get("/api/training/positions").get_json()
    assert training["total"] >= 1
    labels = {item["label"] for item in training["positions"]}
    assert labels <= {"brilliant", "amethyst", "ideal"}
