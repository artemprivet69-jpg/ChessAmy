import chess

import app as A


def test_classify_cp_thresholds():
    assert A.classify_cp(0) == "best"
    assert A.classify_cp(20) == "excellent"
    assert A.classify_cp(35) == "good"
    assert A.classify_cp(80) == "inaccuracy"
    assert A.classify_cp(180) == "mistake"
    assert A.classify_cp(500) == "blunder"


def test_labels_order_and_count():
    assert A.LABELS[:3] == ["amethyst", "brilliant", "ideal"]
    assert len(A.LABELS) == 13
    assert len(set(A.LABELS)) == 13


def test_board_from_moves_respects_start_fen():
    fen = "4k3/8/8/8/8/8/8/4K2R w K - 0 1"
    board = A.board_from_moves([], fen)
    assert board.fen() == fen
    moved = A.board_from_moves([{"uci": "e1e2"}], fen)
    assert moved.piece_at(chess.E2) is not None
    assert moved.piece_at(chess.E1) is None


def test_recovery_code_format():
    code = A.make_recovery_code()
    assert code.startswith("AMY-")
    parts = code.split("-")[1:]
    assert len(parts) == 3
    assert all(len(part) == 4 for part in parts)
    assert A.normalize_recovery("amy-1234-5678-9abc") == "AMY123456789ABC"


def test_settings_are_clamped():
    assert A.normalize_settings({"bot_delay": 99})["bot_delay"] == 5
    assert A.normalize_settings({"bot_delay": -3})["bot_delay"] == 1
    assert A.normalize_settings({"theme": "neon"})["theme"] == "light"
    assert A.normalize_settings({})["theme"] == "light"
