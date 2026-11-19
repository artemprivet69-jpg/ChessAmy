#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chess.amy - локальное шахматное приложение на Flask."""

import atexit
import io
import json
import math
import os
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
APP_DATA_NAME = "ChessAmy"
LOCAL_DATA = Path(
    os.environ.get("LOCALAPPDATA")
    or os.environ.get("APPDATA")
    or str(Path.home())
)
DATA_DIR = LOCAL_DATA / APP_DATA_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "database.db"
LEGACY_DB_PATH = BASE_DIR / "database.db"
STOCKFISH_DIR = BASE_DIR / "stockfish"
SECRET_FILE = DATA_DIR / ".secret_key"
LEGACY_SECRET_FILE = BASE_DIR / ".secret_key"

if not DB_PATH.exists() and LEGACY_DB_PATH.exists():
    shutil.copy2(LEGACY_DB_PATH, DB_PATH)
if not SECRET_FILE.exists() and LEGACY_SECRET_FILE.exists():
    shutil.copy2(LEGACY_SECRET_FILE, SECRET_FILE)


def load_secret():
    if SECRET_FILE.exists():
        value = SECRET_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_hex(32)
    SECRET_FILE.write_text(value, encoding="utf-8")
    return value


def backup_database():
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"database-{stamp}.db"
    if not target.exists():
        try:
            shutil.copy2(DB_PATH, target)
        except OSError:
            return
    backups = sorted(backup_dir.glob("database-*.db"))
    for old in backups[:-20]:
        try:
            old.unlink()
        except OSError:
            pass


BACKUP_NAME_RE = re.compile(r"^database-\d{8}-\d{6}(-\d+)?\.db$")


def backups_dir():
    path = DATA_DIR / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backups():
    items = []
    for path in backups_dir().glob("database-*.db"):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append({
            "name": path.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    items.sort(key=lambda item: item["created"], reverse=True)
    return items


def create_backup_file():
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return None
    target_dir = backups_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"database-{stamp}.db"
    index = 1
    while target.exists():
        target = target_dir / f"database-{stamp}-{index}.db"
        index += 1
    with closing(sqlite3.connect(DB_PATH)) as source, closing(sqlite3.connect(target)) as dest:
        source.backup(dest)
    return target.name


def restore_backup_file(name):
    if not BACKUP_NAME_RE.fullmatch(name or ""):
        return False
    path = backups_dir() / name
    if not path.exists():
        return False
    backup_database()
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(DB_PATH)) as dest:
        source.backup(dest)
    init_db()
    return True


app = Flask(__name__)
app.secret_key = load_secret()
app.json.ensure_ascii = False
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


def find_stockfish():
    if not STOCKFISH_DIR.exists():
        return None
    direct = STOCKFISH_DIR / "stockfish.exe"
    if direct.exists():
        return str(direct)
    for item in sorted(STOCKFISH_DIR.glob("*.exe")):
        if "stockfish" in item.name.lower():
            return str(item)
    return None


STOCKFISH_PATH = find_stockfish()

VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

PIECE_NOM = {
    chess.PAWN: "пешка",
    chess.KNIGHT: "конь",
    chess.BISHOP: "слон",
    chess.ROOK: "ладья",
    chess.QUEEN: "ферзь",
    chess.KING: "король",
}
PIECE_GEN = {
    chess.PAWN: "пешки",
    chess.KNIGHT: "коня",
    chess.BISHOP: "слона",
    chess.ROOK: "ладьи",
    chess.QUEEN: "ферзя",
    chess.KING: "короля",
}
PIECE_ACC = {
    chess.PAWN: "пешку",
    chess.KNIGHT: "коня",
    chess.BISHOP: "слона",
    chess.ROOK: "ладью",
    chess.QUEEN: "ферзя",
    chess.KING: "короля",
}
PIECE_INSTR = {
    chess.PAWN: "пешкой",
    chess.KNIGHT: "конём",
    chess.BISHOP: "слоном",
    chess.ROOK: "ладью",
    chess.QUEEN: "ферзём",
    chess.KING: "королём",
}

LABELS = [
    "amethyst", "brilliant", "ideal", "great", "best", "excellent", "good",
    "book", "inaccuracy", "mistake", "blunder", "miss", "forced",
]

LABEL_MARK = {
    "amethyst": "!!!",
    "brilliant": "!!",
    "ideal": "∞",
    "great": "!",
    "best": "",
    "excellent": "",
    "good": "",
    "book": "",
    "inaccuracy": "?!",
    "mistake": "?",
    "blunder": "??",
    "miss": "x",
    "forced": "",
}

LABEL_RU = {
    "amethyst": "аметистовый ход",
    "brilliant": "блестящий ход",
    "ideal": "идеальный ход",
    "great": "отличный ход",
    "best": "лучший ход",
    "excellent": "превосходный ход",
    "good": "хороший ход",
    "book": "дебютная теория",
    "inaccuracy": "неточность",
    "mistake": "ошибка",
    "blunder": "зевок",
    "miss": "упущенная победа",
    "forced": "вынужденный ход",
}

BOTS = [
    {"elo": 1000, "name": "Пешка Петя", "skill": 0, "depth": 1, "movetime": 60, "color": "#6f8f5f", "cups": 0},
    {"elo": 1100, "name": "Ладья Лена", "skill": 1, "depth": 2, "movetime": 90, "color": "#7b8f4f", "cups": 1},
    {"elo": 1200, "name": "Конь Костя", "skill": 2, "depth": 3, "movetime": 120, "color": "#5f7f8f", "cups": 1},
    {"elo": 1300, "name": "Слон Соня", "skill": 3, "depth": 4, "movetime": 150, "color": "#8f6f5f", "cups": 1},
    {"elo": 1400, "name": "Ферзь Феликс", "skill": 4, "depth": 5, "movetime": 180, "color": "#6f6f9f", "cups": 2},
    {"elo": 1500, "name": "Король Кирилл", "skill": 5, "depth": 6, "movetime": 220, "color": "#9f7f3f", "cups": 2},
    {"elo": 1600, "name": "Гамбит Гриша", "skill": 6, "depth": 7, "movetime": 260, "color": "#4f8f7f", "cups": 2},
    {"elo": 1800, "name": "Рокировка Рита", "skill": 8, "depth": 9, "movetime": 320, "color": "#7f5f7f", "cups": 2},
    {"elo": 2000, "name": "Эндшпиль Эдик", "skill": 10, "depth": 11, "movetime": 400, "color": "#5f6f4f", "cups": 3},
    {"elo": 2200, "name": "Миттельшпиль Мила", "skill": 12, "depth": 13, "movetime": 520, "color": "#8f5f4f", "cups": 3},
    {"elo": 2400, "name": "Дебют Дима", "skill": 13, "depth": 15, "movetime": 650, "color": "#4f6f8f", "cups": 4},
    {"elo": 2600, "name": "Тактик Тимур", "skill": 15, "depth": 17, "movetime": 850, "color": "#6f4f5f", "cups": 4},
    {"elo": 2800, "name": "Стратег Света", "skill": 17, "depth": 19, "movetime": 1100, "color": "#3f5f4f", "cups": 5},
    {"elo": 3200, "name": "Гроссмейстер Глеб", "skill": 19, "depth": 21, "movetime": 1600, "color": "#4f4f6f", "cups": 5},
    {"elo": 3600, "name": "Титан", "skill": 20, "depth": 24, "movetime": 2400, "color": "#3f3f3f", "cups": 5},
]

FAST_BOT = {
    "elo": 1, "name": "Новичок 1 Эло", "skill": 0, "depth": 1,
    "movetime": 5, "color": "#8a8a8a", "cups": 0, "fast": True,
}

ONLINE_FIRST = [
    "Макс", "Лена", "Дима", "Соня", "Костя", "Рита", "Гриша", "Мила",
    "Тимур", "Света", "Глеб", "Ника", "Артём", "Поля", "Егор", "Ася",
]
ONLINE_SECOND = [
    "Гамбит", "Тактик", "Стратег", "Эндшпиль", "Дебют", "Рыцарь",
    "Пешка", "Ферзь", "Слон", "Ладья", "Конь", "Король",
]
ONLINE_COLORS = [
    "#4f8f7f", "#6f8f5f", "#8f6f5f", "#5f6f8f",
    "#8f5f7f", "#7b8f4f", "#5f7f8f", "#9f7f3f",
]

FAST_CONTROLS = ["1+0", "2+1", "3+0", "3+2", "5+0"]
FULL_CONTROLS = ["5+3", "10+0", "10+5", "15+10", "30+0"]
MIN_BOT_THINK_SECONDS = 3.0

TOURNAMENTS = [
    {"num": 1, "name": "Первый шаг", "rounds": 3, "elo_from": 800, "elo_to": 1000, "lives": 3, "title": "Новичок"},
    {"num": 2, "name": "Клубный", "rounds": 3, "elo_from": 1000, "elo_to": 1200, "lives": 3, "title": "Клубный игрок"},
    {"num": 3, "name": "Городской", "rounds": 4, "elo_from": 1200, "elo_to": 1400, "lives": 3, "title": "Городской чемпион"},
    {"num": 4, "name": "Региональный", "rounds": 4, "elo_from": 1400, "elo_to": 1600, "lives": 3, "title": "Региональный мастер"},
    {"num": 5, "name": "Национальный", "rounds": 5, "elo_from": 1600, "elo_to": 1800, "lives": 3, "title": "Национальный мастер"},
    {"num": 6, "name": "Международный", "rounds": 5, "elo_from": 1800, "elo_to": 2000, "lives": 3, "title": "Международный мастер"},
    {"num": 7, "name": "Гроссмейстерский", "rounds": 6, "elo_from": 2000, "elo_to": 2200, "lives": 3, "title": "Гроссмейстер"},
    {"num": 8, "name": "Элитный", "rounds": 6, "elo_from": 2200, "elo_to": 2400, "lives": 3, "title": "Элитный гроссмейстер"},
    {"num": 9, "name": "Турнир Претендентов", "rounds": 7, "elo_from": 2400, "elo_to": 2600, "lives": 3, "title": "Претендент"},
    {"num": 10, "name": "Кубок мира", "rounds": 7, "elo_from": 2600, "elo_to": 2800, "lives": 3, "title": "Обладатель Кубка мира"},
    {"num": 11, "name": "Супертурнир", "rounds": 8, "elo_from": 2800, "elo_to": 2900, "lives": 1, "title": "Супергроссмейстер"},
    {"num": 12, "name": "Мастерс", "rounds": 8, "elo_from": 2900, "elo_to": 3000, "lives": 1, "title": "Мастерс"},
    {"num": 13, "name": "Гранд-финал", "rounds": 9, "elo_from": 3000, "elo_to": 3100, "lives": 1, "title": "Финалист Гранд-финала"},
    {"num": 14, "name": "Абсолютный", "rounds": 9, "elo_from": 3100, "elo_to": 3200, "lives": 1, "title": "Абсолютный мастер"},
    {"num": 15, "name": "Чемпионат мира", "rounds": 10, "elo_from": 3200, "elo_to": 3600, "lives": 1, "title": "Чемпион мира"},
]

TOURNAMENT_BY_NUM = {t["num"]: t for t in TOURNAMENTS}

COACHES = [
    {
        "id": 1, "name": "Артём", "role": "Аналитик",
        "tagline": "Сухо, точно, без скидок",
        "desc": "Любит цифры, варианты и чистую логику. Не хвалит просто так.",
        "color": "#3f6d8c", "gender": "male", "pitch": 0.8, "rate": 1.02,
        "voice_index": 0, "style": "strict",
    },
    {
        "id": 2, "name": "Милана", "role": "Мастер",
        "tagline": "Спокойно и по делу",
        "desc": "Объясняет без спешки, ищет план, а не только тактику.",
        "color": "#8c5f7a", "gender": "female", "pitch": 1.12, "rate": 0.95,
        "voice_index": 1, "style": "calm",
    },
    {
        "id": 3, "name": "Глеб", "role": "Тренер",
        "tagline": "Энергично, с огнём",
        "desc": "Заряжает на борьбу и любит острые продолжения.",
        "color": "#b06a3c", "gender": "male", "pitch": 1.0, "rate": 1.12,
        "voice_index": 2, "style": "energetic",
    },
    {
        "id": 4, "name": "Софья", "role": "Шахматистка",
        "tagline": "Мягко, но требовательно",
        "desc": "Поддерживает и тут же показывает, где потерян темп.",
        "color": "#5f8c6a", "gender": "female", "pitch": 1.22, "rate": 0.92,
        "voice_index": 3, "style": "soft",
    },
    {
        "id": 5, "name": "Пётр", "role": "Профессор",
        "tagline": "Академичный разбор",
        "desc": "Долгие объяснения, термины и внимание к структуре.",
        "color": "#6b5f8c", "gender": "male", "pitch": 0.72, "rate": 0.88,
        "voice_index": 4, "style": "academic",
    },
    {
        "id": 6, "name": "Вера", "role": "Гроссмейстер",
        "tagline": "Уверенно и чётко",
        "desc": "Короткие вердикты и точные рекомендации.",
        "color": "#8c3f4a", "gender": "female", "pitch": 1.05, "rate": 1.0,
        "voice_index": 5, "style": "confident",
    },
    {
        "id": 7, "name": "Тимур", "role": "Тактик",
        "tagline": "Быстро, по вариантам",
        "desc": "Считает форсированные линии и не любит медлить.",
        "color": "#3f8c7a", "gender": "male", "pitch": 1.08, "rate": 1.15,
        "voice_index": 6, "style": "fast",
    },
    {
        "id": 8, "name": "Света", "role": "Стратег",
        "tagline": "Вдумчиво, о планах",
        "desc": "Смотрит на пешечную структуру и слабые поля.",
        "color": "#7a6a3f", "gender": "female", "pitch": 1.18, "rate": 0.85,
        "voice_index": 7, "style": "thoughtful",
    },
    {
        "id": 9, "name": "Дима", "role": "Дебютант",
        "tagline": "Дружелюбно, без давления",
        "desc": "Помогает новичкам и объясняет каждый ярлык.",
        "color": "#4a7a3f", "gender": "male", "pitch": 1.15, "rate": 1.0,
        "voice_index": 8, "style": "friendly",
    },
    {
        "id": 10, "name": "Лев", "role": "Легенда",
        "tagline": "Мудро, как наставник",
        "desc": "Опытный голос, который видит партию целиком.",
        "color": "#5a5a5a", "gender": "male", "pitch": 0.65, "rate": 0.82,
        "voice_index": 9, "style": "mentor",
    },
]
COACH_BY_ID = {item["id"]: item for item in COACHES}
DEFAULT_COACH = COACHES[0]


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    username_lower TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    elo INTEGER NOT NULL DEFAULT 500,
    cups INTEGER NOT NULL DEFAULT 0,
    titles TEXT NOT NULL DEFAULT '[]',
    remember_token TEXT,
    coach_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    mode TEXT NOT NULL,
    bot_name TEXT,
    bot_elo INTEGER,
    user_color TEXT,
    time_control TEXT,
    start_fen TEXT,
    pgn TEXT NOT NULL DEFAULT '',
    moves TEXT NOT NULL DEFAULT '[]',
    result TEXT,
    reason TEXT,
    analysis TEXT,
    tournament_number INTEGER,
    round_number INTEGER,
    white_ms INTEGER,
    black_ms INTEGER,
    last_ts REAL,
    clock_active TEXT,
    timed INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    lives INTEGER NOT NULL,
    current_round INTEGER NOT NULL DEFAULT 0,
    bracket TEXT NOT NULL DEFAULT '{}',
    won INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, number),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS tournament_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    opens_at TEXT NOT NULL,
    UNIQUE (user_id, number),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


def init_db():
    with closing(get_db()) as db:
        db.executescript(SCHEMA)
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "coach_id" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN coach_id INTEGER")
        if "recovery_hash" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN recovery_hash TEXT")
        game_columns = {row[1] for row in db.execute("PRAGMA table_info(games)")}
        if "start_fen" not in game_columns:
            db.execute("ALTER TABLE games ADD COLUMN start_fen TEXT")
        db.commit()


init_db()
backup_database()


BOARD_THEMES = {
    "green": ("#eeeed2", "#769656"),
    "brown": ("#f0d9b5", "#b58863"),
    "blue": ("#dee3e6", "#8ca2ad"),
    "gray": ("#e9e6e1", "#9a9a90"),
    "purple": ("#e8e1f0", "#8a72ab"),
    "wood": ("#e8d3b0", "#a07d52"),
    "dark": ("#8a8a80", "#4a4a44"),
}
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SETTINGS_DEFAULTS = {
    "bot_delay": 3,
    "theme": "light",
    "sound": True,
    "coordinates": True,
    "board_theme": "green",
    "board_light": BOARD_THEMES["green"][0],
    "board_dark": BOARD_THEMES["green"][1],
    "piece_speed": 220,
}


def normalize_settings(raw):
    data = dict(SETTINGS_DEFAULTS)
    if isinstance(raw, dict):
        data.update(raw)
    try:
        delay = float(data.get("bot_delay"))
    except (TypeError, ValueError):
        delay = float(SETTINGS_DEFAULTS["bot_delay"])
    data["bot_delay"] = max(1.0, min(5.0, round(delay, 1)))
    theme = str(data.get("theme") or "light").strip().lower()
    data["theme"] = "dark" if theme == "dark" else "light"
    data["sound"] = bool(data.get("sound", True))
    data["coordinates"] = bool(data.get("coordinates", True))
    board_theme = str(data.get("board_theme") or "green").strip().lower()
    if board_theme != "custom" and board_theme not in BOARD_THEMES:
        board_theme = "green"
    data["board_theme"] = board_theme
    if board_theme == "custom":
        light = str(data.get("board_light") or "").strip()
        dark = str(data.get("board_dark") or "").strip()
        data["board_light"] = light if HEX_COLOR_RE.match(light) else BOARD_THEMES["green"][0]
        data["board_dark"] = dark if HEX_COLOR_RE.match(dark) else BOARD_THEMES["green"][1]
    else:
        data["board_light"], data["board_dark"] = BOARD_THEMES[board_theme]
    try:
        speed = int(float(data.get("piece_speed")))
    except (TypeError, ValueError):
        speed = int(SETTINGS_DEFAULTS["piece_speed"])
    data["piece_speed"] = max(120, min(600, speed))
    return data


def get_user_settings(user_id):
    if not user_id:
        return normalize_settings({})
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT data FROM user_settings WHERE user_id=?", (user_id,)
        ).fetchone()
    stored = {}
    if row is not None:
        try:
            stored = json.loads(row["data"])
        except (TypeError, ValueError):
            stored = {}
    return normalize_settings(stored)


def save_user_settings(user_id, values):
    if not user_id:
        return normalize_settings(values)
    merged = get_user_settings(user_id)
    if isinstance(values, dict):
        merged.update(values)
    merged = normalize_settings(merged)
    with closing(get_db()) as db:
        db.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, data) VALUES (?,?)",
            (user_id, json.dumps(merged, ensure_ascii=False)),
        )
        db.commit()
    return merged


def bot_delay_for(row):
    user_id = None
    if row is not None:
        try:
            user_id = row["user_id"]
        except (IndexError, KeyError):
            user_id = None
    return float(get_user_settings(user_id)["bot_delay"])


def fetch_user(uid):
    if not uid:
        return None
    with closing(get_db()) as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return row


def current_user():
    uid = session.get("uid")
    user = fetch_user(uid)
    if user is None:
        session.pop("uid", None)
    return user


def coach_for_user(user):
    if user is None:
        return DEFAULT_COACH
    try:
        coach_id = user["coach_id"]
    except (IndexError, KeyError):
        coach_id = None
    return COACH_BY_ID.get(coach_id or DEFAULT_COACH["id"], DEFAULT_COACH)


def user_json(user):
    if user is None:
        return None
    titles = []
    try:
        titles = json.loads(user["titles"])
    except (TypeError, ValueError):
        titles = []
    try:
        coach_id = user["coach_id"]
    except (IndexError, KeyError):
        coach_id = None
    coach = COACH_BY_ID.get(coach_id or DEFAULT_COACH["id"], DEFAULT_COACH)
    return {
        "id": user["id"],
        "username": user["username"],
        "elo": user["elo"],
        "cups": user["cups"],
        "titles": titles,
        "is_legend": user["elo"] >= 4000,
        "coach_id": coach_id,
        "coach": {
            "id": coach["id"],
            "name": coach["name"],
            "role": coach["role"],
            "color": coach["color"],
        },
        "needs_coach": bool(coach_id is None),
    }


@app.context_processor
def inject_globals():
    user = current_user()
    return {
        "current_user": user,
        "current_user_json": user_json(user),
        "ui_settings": get_user_settings(user["id"]) if user is not None else normalize_settings({}),
        "current_coach": coach_for_user(user),
        "coaches": COACHES,
        "stockfish_ready": bool(STOCKFISH_PATH),
        "bot_list": BOTS,
        "fast_bot": FAST_BOT,
        "tournament_list": TOURNAMENTS,
        "fast_controls": FAST_CONTROLS,
        "full_controls": FULL_CONTROLS,
    }


class EnginePool:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.engine = None
        self.broken = not bool(path)

    def _ensure(self):
        if self.engine is not None:
            return self.engine
        if self.broken or not self.path or not os.path.exists(self.path):
            return None
        try:
            engine = chess.engine.SimpleEngine.popen_uci(self.path)
            try:
                engine.configure({"Threads": 1, "Hash": 128})
            except chess.engine.EngineError:
                pass
            self.engine = engine
            return engine
        except Exception:
            self.broken = True
            return None

    def _drop(self):
        if self.engine is not None:
            try:
                self.engine.quit()
            except Exception:
                pass
        self.engine = None

    def available(self):
        with self.lock:
            return self._ensure() is not None

    def analyse(self, board, depth=12, multipv=2):
        with self.lock:
            engine = self._ensure()
            if engine is None:
                return None
            try:
                engine.configure({"Skill Level": 20})
            except chess.engine.EngineError:
                pass
            try:
                infos = engine.analyse(
                    board, chess.engine.Limit(depth=depth), multipv=multipv
                )
                return infos
            except Exception:
                self._drop()
                return None

    def play(self, board, depth, movetime, skill=20):
        with self.lock:
            engine = self._ensure()
            if engine is None:
                return None
            try:
                engine.configure({"Skill Level": max(0, min(20, int(skill)))})
            except chess.engine.EngineError:
                pass
            limit = chess.engine.Limit(
                depth=max(1, int(depth)),
                time=max(0.01, float(movetime) / 1000.0),
            )
            try:
                result = engine.play(board, limit)
                return result.move
            except Exception:
                self._drop()
                return None


ENGINE = EnginePool(STOCKFISH_PATH)


def _shutdown_engine():
    try:
        ENGINE._drop()
    except Exception:
        pass


atexit.register(_shutdown_engine)


def static_eval(board):
    if board.is_checkmate():
        return -99999 if board.turn == chess.WHITE else 99999
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = 0
    center = [chess.D4, chess.E4, chess.D5, chess.E5]
    for square, piece in board.piece_map().items():
        value = VALUES[piece.piece_type]
        pawn_row = chess.square_rank(square)
        if piece.color == chess.WHITE:
            score += value
            if piece.piece_type == chess.PAWN:
                score += pawn_row * 6
            if square in center:
                score += 12
            elif chess.square_file(square) in (3, 4):
                score += 5
        else:
            score -= value
            if piece.piece_type == chess.PAWN:
                score -= (7 - pawn_row) * 6
            if square in center:
                score -= 12
            elif chess.square_file(square) in (3, 4):
                score -= 5
    try:
        mobility = board.legal_moves.count()
        score += mobility * 2 if board.turn == chess.WHITE else -mobility * 2
    except Exception:
        pass
    return score


def fallback_search(board, depth=2):
    legal = list(board.legal_moves)
    if not legal:
        return None, 0
    best_move = None
    best_score = -10 ** 9
    ordered = sorted(legal, key=lambda m: 1 if board.is_capture(m) else 0, reverse=True)
    for move in ordered:
        board.push(move)
        if board.is_checkmate():
            score = 100000
        elif depth <= 1:
            score = -static_eval(board)
        else:
            score = -fallback_search(board, depth - 1)[1]
        board.pop()
        if score > best_score:
            best_score = score
            best_move = move
    return best_move, best_score


def engine_eval(board, depth=12):
    infos = ENGINE.analyse(board, depth=depth, multipv=2)
    if not infos:
        move, score = fallback_search(board, 1)
        return {
            "cp": score,
            "best": move,
            "second_cp": score,
            "mate": None,
        }
    first = infos[0]
    pov = first.get("score")
    cp = 0
    mate = None
    if pov is not None:
        pov = pov.pov(board.turn)
        mate = pov.mate()
        cp = pov.score(mate_score=10000)
    best = None
    pv = first.get("pv")
    if pv:
        best = pv[0]
    second_cp = cp
    if len(infos) > 1 and infos[1].get("score") is not None:
        second_cp = infos[1]["score"].pov(board.turn).score(mate_score=10000)
    return {"cp": cp, "best": best, "second_cp": second_cp, "mate": mate}


def classify_cp(cp_loss):
    if cp_loss <= 5:
        return "best"
    if cp_loss <= 20:
        return "excellent"
    if cp_loss <= 50:
        return "good"
    if cp_loss <= 100:
        return "inaccuracy"
    if cp_loss <= 200:
        return "mistake"
    return "blunder"


def is_sacrifice(board, move):
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type == chess.KING:
        return False
    captured = board.piece_at(move.to_square)
    if captured is not None and VALUES[captured.piece_type] >= VALUES[piece.piece_type]:
        return False
    probe = board.copy()
    probe.push(move)
    moved = probe.piece_at(move.to_square)
    if moved is None:
        return False
    if probe.is_checkmate():
        return False
    attackers = probe.attackers(not moved.color, move.to_square)
    if not attackers:
        return False
    cheapest = min(VALUES[probe.piece_at(a).piece_type] for a in attackers)
    defenders = probe.attackers(moved.color, move.to_square)
    if not defenders:
        return True
    return cheapest < VALUES[moved.piece_type]


def mate_in_one_coverage(board_after):
    if board_after.is_checkmate() or board_after.is_stalemate():
        return 0, 0
    replies = list(board_after.legal_moves)
    if not replies:
        return 0, 0
    probe = board_after.copy()
    punishing = 0
    for reply in replies:
        probe.push(reply)
        found = False
        for attack in list(probe.legal_moves):
            probe.push(attack)
            if probe.is_checkmate():
                found = True
            probe.pop()
            if found:
                break
        probe.pop()
        if found:
            punishing += 1
    return punishing, len(replies)


def has_mate_in_one_threat(board_after):
    punishing, total = mate_in_one_coverage(board_after)
    return total > 0 and punishing == total


def has_mate_in_one_reply(board_after):
    punishing, total = mate_in_one_coverage(board_after)
    return total > 0 and punishing > 0


def classify_position(board, move, before_cp, after_cp, best_move=None, second_cp=None, ply=0):
    piece = board.piece_at(move.from_square)
    loss = max(0, int(before_cp - after_cp))
    second = before_cp if second_cp is None else int(second_cp)
    gap = int(before_cp) - second
    try:
        legal_count = board.legal_moves.count()
    except Exception:
        legal_count = 0
    sacrifice = is_sacrifice(board, move) if piece else False
    only_saving = (second <= -250 and before_cp >= -150) or (gap >= 300 and before_cp >= -50)
    mate_in_one = False
    forced_mate = False
    mate_threat = False
    probe_after = None
    if sacrifice and loss <= 20 and after_cp >= before_cp - 10:
        probe_after = board.copy()
        probe_after.push(move)
        mate_in_one = has_mate_in_one_threat(probe_after)
        forced_mate = after_cp >= 9000
    if not mate_in_one and not forced_mate and loss <= 50 and after_cp >= -50:
        if probe_after is None:
            probe_after = board.copy()
            probe_after.push(move)
        mate_threat = has_mate_in_one_reply(probe_after)
    if legal_count == 1:
        label = "forced"
    elif mate_in_one:
        label = "amethyst"
    elif forced_mate:
        label = "brilliant"
    elif mate_threat:
        label = "ideal"
    elif before_cp >= 250 and after_cp <= 50 and loss >= 150:
        label = "miss"
    elif ply < 6 and loss <= 25:
        label = "book"
    elif loss <= 20 and (gap >= 150 and before_cp >= -100):
        label = "great"
    else:
        label = classify_cp(loss)
    return label, {
        "loss": loss,
        "sacrifice": bool(sacrifice),
        "only_saving": bool(only_saving),
        "gap": gap,
        "legal_count": legal_count,
        "mate_in_one": bool(mate_in_one),
        "forced_mate": bool(forced_mate),
        "mate_threat": bool(mate_threat),
    }


def fast_bot_move(board):
    legal = list(board.legal_moves)
    if not legal:
        return None
    if random.random() < 0.034:
        def score(move):
            value = 0
            target = board.piece_at(move.to_square)
            if target is not None:
                value += VALUES[target.piece_type] * 5
            if move.promotion:
                value += VALUES[move.promotion] * 3
            probe = board.copy()
            probe.push(move)
            if probe.is_checkmate():
                value += 100000
            elif probe.is_check():
                value += 60
            return value
        return max(legal, key=score)
    return random.choice(legal)


def pick_bot_move(board, bot):
    if bot.get("fast"):
        return fast_bot_move(board)
    move = ENGINE.play(board, bot["depth"], bot["movetime"], bot.get("skill", 20))
    if move is None:
        move = fallback_search(board, 2)[0]
    return move


def bot_by_elo(elo):
    if elo <= 1:
        return FAST_BOT
    return min(BOTS, key=lambda b: abs(b["elo"] - elo))


def online_elo_bounds(elo):
    elo = int(elo or 0)
    return max(100, elo - 200), min(4000, elo + 100)


def random_online_name(used=None):
    used = set(used or [])
    for _ in range(60):
        name = f"{random.choice(ONLINE_FIRST)} {random.choice(ONLINE_SECOND)}"
        if name not in used:
            return name
    return f"Бот {random.randint(100, 999)}"


def make_online_bot(elo, name=None):
    elo = max(100, min(4000, int(elo)))
    skill = max(0, min(20, round((elo - 700) / 145)))
    depth = max(1, min(24, round(1 + (elo - 300) / 145)))
    movetime = max(40, min(2400, round(40 + (elo - 300) * 0.6)))
    return {
        "elo": elo,
        "name": name or random_online_name(),
        "skill": skill,
        "depth": depth,
        "movetime": movetime,
        "color": random.choice(ONLINE_COLORS),
        "cups": random.randint(0, 5),
        "online": True,
    }


def online_bots_for(elo, count=6):
    low, high = online_elo_bounds(elo)
    bots = []
    used = set()
    for _ in range(count):
        bot_elo = random.randint(low, high)
        name = random_online_name(used)
        used.add(name)
        bots.append(make_online_bot(bot_elo, name))
    return sorted(bots, key=lambda item: item["elo"])


def elo_k(elo):
    if elo < 1000:
        return 40
    if elo < 1500:
        return 32
    if elo < 2000:
        return 24
    if elo < 2500:
        return 16
    if elo < 3000:
        return 12
    return 8


def apply_elo(user, bot_elo, score):
    elo = user["elo"]
    expected = 1.0 / (1.0 + 10 ** ((bot_elo - elo) / 400.0))
    k = elo_k(elo)
    if elo >= 3800:
        k = min(k, 4)
    new_elo = int(round(elo + k * (score - expected)))
    new_elo = max(0, min(4000, new_elo))
    titles = json.loads(user["titles"] or "[]")
    if new_elo >= 4000 and "Легенда" not in titles:
        titles.append("Легенда")
    with closing(get_db()) as db:
        db.execute(
            "UPDATE users SET elo=?, titles=? WHERE id=?",
            (new_elo, json.dumps(titles, ensure_ascii=False), user["id"]),
        )
        db.commit()
    return new_elo


def validate_username(name):
    if not isinstance(name, str):
        return "Ник должен быть строкой"
    name = name.strip()
    if not 3 <= len(name) <= 20:
        return "Ник: от 3 до 20 символов"
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9_!?]+", name):
        return "В нике допустимы буквы, цифры и символы _ ! ?"
    return None


def validate_password(password):
    if not isinstance(password, str):
        return "Пароль должен быть строкой"
    if not 4 <= len(password) <= 20:
        return "Пароль: от 4 до 20 символов"
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9_!?]+", password):
        return "В пароле допустимы буквы, цифры и символы _ ! ?"
    if not re.search(r"[A-Za-zА-Яа-яЁё]", password):
        return "Пароль должен содержать хотя бы одну букву"
    if not re.search(r"[0-9]", password):
        return "Пароль должен содержать хотя бы одну цифру"
    return None


def parse_time_control(tc):
    match = re.fullmatch(r"(\d+)\+(\d+)", tc or "")
    if not match:
        return 300000, 0, False
    base = int(match.group(1)) * 60000
    inc = int(match.group(2)) * 1000
    timed = tc != "1+0"
    return base, inc, timed


def build_pgn(moves, headers, start_fen=None):
    game = chess.pgn.Game()
    for key, value in headers.items():
        game.headers[key] = str(value)
    if start_fen:
        try:
            start_board = chess.Board(start_fen)
        except ValueError:
            start_board = chess.Board()
        if start_board.fen() != chess.Board().fen():
            game.setup(start_board)
    node = game
    for item in moves:
        try:
            node = node.add_variation(chess.Move.from_uci(item["uci"]))
        except ValueError:
            break
    return str(game)


def load_game(gid):
    with closing(get_db()) as db:
        row = db.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    return row


def save_game(gid, **fields):
    if not fields:
        return
    columns = ", ".join(f"{key}=?" for key in fields)
    values = list(fields.values()) + [gid]
    with closing(get_db()) as db:
        db.execute(f"UPDATE games SET {columns} WHERE id=?", values)
        db.commit()


def game_moves(row):
    try:
        return json.loads(row["moves"] or "[]")
    except (TypeError, ValueError):
        return []


def board_from_moves(moves, fen=None):
    try:
        board = chess.Board(fen) if fen else chess.Board()
    except ValueError:
        board = chess.Board()
    for item in moves:
        try:
            board.push(chess.Move.from_uci(item["uci"]))
        except ValueError:
            break
    return board


def board_for(row):
    try:
        fen = row["start_fen"]
    except (IndexError, KeyError):
        fen = None
    return board_from_moves(game_moves(row), fen)


def create_game(user_id, mode, bot, user_color, tc, tournament_number=None, round_number=None, start_fen=None):
    base, inc, timed = parse_time_control(tc)
    now = now_utc()
    with closing(get_db()) as db:
        cursor = db.execute(
            """INSERT INTO games
            (user_id, mode, bot_name, bot_elo, user_color, time_control, start_fen, pgn, moves,
             tournament_number, round_number, white_ms, black_ms, last_ts, clock_active,
             timed, status, created_at)
            VALUES (?,?,?,?,?,?,?,'','[]',?,?,?,?,?,?,?,'active',?)""",
            (
                user_id, mode, bot["name"], bot["elo"], user_color, tc, start_fen,
                tournament_number, round_number, base, base, time.time(),
                "white", 1 if timed else 0, iso(now),
            ),
        )
        gid = cursor.lastrowid
        db.commit()
    if user_color == "black":
        start_bot_turn(gid)
    return gid


def tick_clock(row):
    if not row["timed"] or row["status"] != "active":
        return row["white_ms"], row["black_ms"], time.time(), None
    board = board_from_moves(game_moves(row), row["start_fen"])
    active = "white" if board.turn == chess.WHITE else "black"
    last = row["last_ts"] or time.time()
    elapsed = max(0, int((time.time() - last) * 1000))
    white_ms = row["white_ms"]
    black_ms = row["black_ms"]
    if active == "white":
        white_ms -= elapsed
    else:
        black_ms -= elapsed
    last = time.time()
    timed_out = None
    if white_ms <= 0:
        timed_out = "black"
    elif black_ms <= 0:
        timed_out = "white"
    return white_ms, black_ms, last, timed_out


def clock_after_move(row, board_before):
    if not row["timed"]:
        return row["white_ms"], row["black_ms"]
    base, inc, _ = parse_time_control(row["time_control"])
    white_ms = row["white_ms"]
    black_ms = row["black_ms"]
    if board_before.turn == chess.WHITE:
        white_ms += inc
    else:
        black_ms += inc
    return white_ms, black_ms


def result_after_board(board, user_color):
    if board.is_checkmate():
        winner = "black" if board.turn == chess.WHITE else "white"
        return ("win" if winner == user_color else "loss"), "checkmate"
    if board.is_stalemate():
        return "draw", "stalemate"
    if board.is_insufficient_material():
        return "draw", "insufficient"
    if board.is_seventyfive_moves():
        return "draw", "seventyfive"
    if board.is_fivefold_repetition():
        return "draw", "fivefold"
    if board.can_claim_fifty_moves():
        return "draw", "fifty"
    if board.can_claim_threefold_repetition():
        return "draw", "repetition"
    return None, None


def finish_game(gid, result, reason):
    row = load_game(gid)
    if row is None or row["status"] == "finished":
        return row
    moves = game_moves(row)
    headers = {
        "Event": "Chess.amy",
        "Site": "localhost",
        "White": row["user_color"] == "white" and "You" or row["bot_name"],
        "Black": row["user_color"] == "black" and "You" or row["bot_name"],
        "Result": "1-0" if result == "win" and row["user_color"] == "white" else "",
        "TimeControl": row["time_control"] or "",
        "Termination": reason or "",
    }
    pgn = build_pgn(moves, headers, row["start_fen"])
    with closing(get_db()) as db:
        db.execute(
            "UPDATE games SET status='finished', result=?, reason=?, pgn=?, finished_at=? WHERE id=?",
            (result, reason, pgn, iso(now_utc()), gid),
        )
        db.commit()
    if row["mode"] in ("online", "tournament") and row["user_id"]:
        user = fetch_user(row["user_id"])
        if user:
            score = 1.0 if result == "win" else (0.5 if result == "draw" else 0.0)
            apply_elo(user, row["bot_elo"] or 1000, score)
    if row["mode"] == "tournament" and row["tournament_number"]:
        process_tournament_result(gid)
    return load_game(gid)


BOT_JOBS = {}
BOT_JOBS_LOCK = threading.Lock()


def bot_thinking(gid):
    with BOT_JOBS_LOCK:
        job = BOT_JOBS.get(gid)
        return bool(job and job.is_alive())


def _run_bot_turn(gid):
    try:
        play_bot_turn(gid)
    except Exception:
        app.logger.exception("Ошибка хода бота в партии %s", gid)
    finally:
        with BOT_JOBS_LOCK:
            BOT_JOBS.pop(gid, None)


def start_bot_turn(gid):
    with BOT_JOBS_LOCK:
        job = BOT_JOBS.get(gid)
        if job and job.is_alive():
            return False
        thread = threading.Thread(
            target=_run_bot_turn, args=(gid,), daemon=True, name=f"bot-turn-{gid}"
        )
        BOT_JOBS[gid] = thread
    thread.start()
    return True


def play_bot_turn(gid, delay=None):
    row = load_game(gid)
    if row is None or row["status"] == "finished":
        return
    moves = game_moves(row)
    board = board_from_moves(moves, row["start_fen"])
    user_color = row["user_color"]
    if (board.turn == chess.WHITE and user_color == "white") or (board.turn == chess.BLACK and user_color == "black"):
        return
    if delay is None:
        delay = bot_delay_for(row)
    white_ms, black_ms, last, timed_out = tick_clock(row)
    if timed_out:
        result = "loss" if timed_out == user_color else "win"
        finish_game(gid, result, "timeout")
        return
    bot = bot_by_elo(row["bot_elo"] or 1000)
    if row["bot_elo"] == 1:
        bot = FAST_BOT
    think_started = time.monotonic()
    move = pick_bot_move(board, bot)
    if move is None:
        result, reason = result_after_board(board, user_color)
        finish_game(gid, result or "draw", reason or "stalemate")
        return
    elapsed = time.monotonic() - think_started
    if elapsed < delay:
        time.sleep(delay - elapsed)
    board_before = board.copy()
    san = board.san(move)
    board.push(move)
    moves.append({
        "uci": move.uci(),
        "san": san,
        "color": "white" if board_before.turn == chess.WHITE else "black",
    })
    white_ms, black_ms = clock_after_move(
        {"timed": row["timed"], "time_control": row["time_control"],
         "white_ms": white_ms, "black_ms": black_ms},
        board_before,
    )
    active = "white" if board.turn == chess.WHITE else "black"
    save_game(
        gid, moves=json.dumps(moves, ensure_ascii=False),
        white_ms=white_ms, black_ms=black_ms, last_ts=last, clock_active=active,
    )
    result, reason = result_after_board(board, user_color)
    if result:
        finish_game(gid, result, reason)


def apply_user_move(gid, from_sq, to_sq, promotion=None):
    row = load_game(gid)
    if row is None:
        return None, "Партия не найдена"
    if row["status"] == "finished":
        return None, "Партия уже завершена"
    moves = game_moves(row)
    board = board_from_moves(moves, row["start_fen"])
    user_color = row["user_color"]
    if (board.turn == chess.WHITE and user_color != "white") or (board.turn == chess.BLACK and user_color != "black"):
        return None, "Сейчас не твой ход"
    white_ms, black_ms, last, timed_out = tick_clock(row)
    if timed_out:
        result = "loss" if timed_out == user_color else "win"
        finish_game(gid, result, "timeout")
        return None, "Время вышло"
    try:
        move = chess.Move.from_uci(f"{from_sq}{to_sq}{promotion or ''}")
    except ValueError:
        return None, "Некорректный ход"
    if move not in board.legal_moves:
        return None, "Так ходить нельзя"
    board_before = board.copy()
    san = board.san(move)
    board.push(move)
    moves.append({
        "uci": move.uci(),
        "san": san,
        "color": "white" if board_before.turn == chess.WHITE else "black",
    })
    white_ms, black_ms = clock_after_move(
        {"timed": row["timed"], "time_control": row["time_control"],
         "white_ms": white_ms, "black_ms": black_ms},
        board_before,
    )
    active = "white" if board.turn == chess.WHITE else "black"
    save_game(
        gid, moves=json.dumps(moves, ensure_ascii=False),
        white_ms=white_ms, black_ms=black_ms, last_ts=last, clock_active=active,
    )
    result, reason = result_after_board(board, user_color)
    if result:
        finish_game(gid, result, reason)
        return load_game(gid), None
    start_bot_turn(gid)
    return load_game(gid), None


def game_state(row):
    if row is None:
        return None
    moves = game_moves(row)
    board = board_from_moves(moves, row["start_fen"])
    if row["status"] == "active" and row["timed"]:
        white_ms, black_ms, last, timed_out = tick_clock(row)
        if timed_out:
            result = "loss" if timed_out == row["user_color"] else "win"
            row = finish_game(row["id"], result, "timeout")
            board = board_from_moves(game_moves(row), row["start_fen"])
        else:
            with closing(get_db()) as db:
                db.execute(
                    "UPDATE games SET white_ms=?, black_ms=?, last_ts=? WHERE id=?",
                    (white_ms, black_ms, last, row["id"]),
                )
                db.commit()
            row = load_game(row["id"])
    if row["status"] == "active":
        result, reason = result_after_board(board, row["user_color"])
        if result:
            row = finish_game(row["id"], result, reason)
            board = board_from_moves(game_moves(row), row["start_fen"])
    legal = []
    if row["status"] == "active":
        legal = [move.uci() for move in board.legal_moves]
    last_move = None
    if moves:
        uci = moves[-1]["uci"]
        last_move = {"from": uci[:2], "to": uci[2:4]}
    return {
        "id": row["id"],
        "fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "user_color": row["user_color"],
        "bot": {"name": row["bot_name"], "elo": row["bot_elo"]},
        "legal": legal,
        "moves": moves,
        "last_move": last_move,
        "status": row["status"],
        "result": row["result"],
        "reason": row["reason"],
        "time_control": row["time_control"],
        "timed": bool(row["timed"]),
        "clocks": {
            "white_ms": max(0, row["white_ms"] or 0),
            "black_ms": max(0, row["black_ms"] or 0),
            "active": row["clock_active"],
        },
        "check": board.is_check(),
        "mode": row["mode"],
        "tournament_number": row["tournament_number"],
        "round_number": row["round_number"],
        "thinking": bot_thinking(row["id"]),
    }


def init_tournament_access(db, user_id):
    now = now_utc()
    for item in TOURNAMENTS[1:]:
        span = (item["num"] - 2) / 13.0
        days = 10 + span * 38 + random.uniform(-3.5, 3.5)
        days = max(10.0, min(60.0, days))
        db.execute(
            "INSERT OR IGNORE INTO tournament_access (user_id, number, opens_at) VALUES (?,?,?)",
            (user_id, item["num"], iso(now + timedelta(days=days))),
        )


def access_map(user_id):
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT number, opens_at FROM tournament_access WHERE user_id=?", (user_id,)
        ).fetchall()
    return {row["number"]: row["opens_at"] for row in rows}


def tournament_is_open(user_id, num):
    if num == 1:
        return True, None
    opens = access_map(user_id).get(num)
    if not opens:
        return False, None
    dt = parse_iso(opens)
    if dt is None:
        return False, None
    return now_utc() >= dt, opens


def days_left_text(opens_at):
    dt = parse_iso(opens_at)
    if dt is None:
        return "недоступно"
    seconds = (dt - now_utc()).total_seconds()
    if seconds <= 0:
        return "открыт"
    days = int(math.ceil(seconds / 86400.0))
    if days <= 1:
        hours = max(1, int(math.ceil(seconds / 3600.0)))
        return f"{hours} ч"
    return f"{days} дн."


def tournament_info_for_user(user):
    access = access_map(user["id"])
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT * FROM tournaments WHERE user_id=?", (user["id"],)
        ).fetchall()
    played = {row["number"]: row for row in rows}
    result = []
    for item in TOURNAMENTS:
        num = item["num"]
        if num == 1:
            unlocked = True
            opens_at = None
            left = "открыт"
        else:
            opens_at = access.get(num)
            dt = parse_iso(opens_at)
            unlocked = bool(dt and now_utc() >= dt)
            left = days_left_text(opens_at)
        record = played.get(num)
        result.append({
            "num": num,
            "name": item["name"],
            "rounds": item["rounds"],
            "elo_from": item["elo_from"],
            "elo_to": item["elo_to"],
            "lives": item["lives"],
            "title": item["title"],
            "unlocked": unlocked,
            "opens_at": opens_at,
            "left": left,
            "status": record["status"] if record else None,
            "lives_left": record["lives"] if record else item["lives"],
            "won": bool(record["won"]) if record else False,
        })
    return result


def pick_tournament_bot(item, used=None):
    used = used or set()
    band = [bot for bot in BOTS if item["elo_from"] <= bot["elo"] <= item["elo_to"]]
    if not band:
        band = [bot for bot in BOTS if abs(bot["elo"] - item["elo_to"]) <= 400]
    if not band:
        band = BOTS
    fresh = [bot for bot in band if bot["name"] not in used] or band
    return random.choice(fresh)


def quick_bot_move(board, elo):
    legal = list(board.legal_moves)
    if not legal:
        return None
    strength = max(0.05, min(0.95, (elo - 700) / 3200.0))
    if random.random() > strength:
        return random.choice(legal)
    best = None
    best_score = -10 ** 9
    for move in legal:
        score = 0
        target = board.piece_at(move.to_square)
        if target is not None:
            score += VALUES[target.piece_type]
        probe = board.copy()
        probe.push(move)
        if probe.is_checkmate():
            score += 50000
        elif probe.is_check():
            score += 40
        if probe.is_attacked_by(probe.turn, move.to_square):
            moved = probe.piece_at(move.to_square)
            if moved is not None and probe.piece_at(move.to_square) is not None:
                attackers = probe.attackers(probe.turn, move.to_square)
                if attackers and not probe.attackers(not probe.turn, move.to_square):
                    score -= VALUES[moved.piece_type]
        score += random.random() * 120
        if score > best_score:
            best_score = score
            best = move
    return best or random.choice(legal)


def simulate_bot_game(white_bot, black_bot, tournament_number):
    board = chess.Board()
    moves = []
    for _ in range(140):
        if board.is_game_over(claim_draw=True):
            break
        bot = white_bot if board.turn == chess.WHITE else black_bot
        move = quick_bot_move(board, bot["elo"])
        if move is None:
            break
        san = board.san(move)
        board.push(move)
        moves.append({
            "uci": move.uci(),
            "san": san,
            "color": "white" if board.turn == chess.BLACK else "black",
        })
    if board.is_checkmate():
        result = "1-0" if board.turn == chess.BLACK else "0-1"
    else:
        result = "1/2-1/2"
    headers = {
        "Event": f"Турнир {tournament_number}",
        "Site": "localhost",
        "White": white_bot["name"],
        "Black": black_bot["name"],
        "Result": result,
    }
    pgn = build_pgn(moves, headers)
    with closing(get_db()) as db:
        cursor = db.execute(
            """INSERT INTO games
            (user_id, mode, bot_name, bot_elo, user_color, time_control, pgn, moves,
             result, reason, tournament_number, white_ms, black_ms, timed, status,
             created_at, finished_at)
            VALUES (NULL,'tournament_bot',?,?, 'white', '', ?, ?, ?, 'simulated', ?, 0, 0, 0,
                    'finished', ?, ?)""",
            (
                f"{white_bot['name']} - {black_bot['name']}",
                max(white_bot["elo"], black_bot["elo"]),
                pgn, json.dumps(moves, ensure_ascii=False),
                result, tournament_number, iso(now_utc()), iso(now_utc()),
            ),
        )
        gid = cursor.lastrowid
        db.commit()
    return gid, result


def round_name(index, total):
    remaining = total - index
    if remaining == 1:
        return "Финал"
    if remaining == 2:
        return "Полуфинал"
    if remaining == 3:
        return "1/4 финала"
    return f"Раунд {index + 1}"


def build_bracket(item):
    used = set()
    rounds = []
    for index in range(item["rounds"]):
        opponent = pick_tournament_bot(item, used)
        used.add(opponent["name"])
        user_color = random.choice(["white", "black"])
        player_match = {
            "kind": "player",
            "white": "Ты" if user_color == "white" else opponent["name"],
            "black": opponent["name"] if user_color == "white" else "Ты",
            "opponent": opponent["name"],
            "bot_elo": opponent["elo"],
            "user_color": user_color,
            "game_id": None,
            "result": None,
        }
        showcases = []
        for _ in range(1 if index < item["rounds"] - 1 else 2):
            white_bot = pick_tournament_bot(item)
            black_bot = pick_tournament_bot(item)
            if white_bot["name"] == black_bot["name"]:
                black_bot = BOTS[(BOTS.index(white_bot) + 3) % len(BOTS)]
            gid, result = simulate_bot_game(white_bot, black_bot, item["num"])
            showcases.append({
                "kind": "bot",
                "white": white_bot["name"],
                "black": black_bot["name"],
                "game_id": gid,
                "result": result,
                "round": index + 1,
            })
        rounds.append({
            "round": index + 1,
            "name": round_name(index, item["rounds"]),
            "player": player_match,
            "bot_games": showcases,
        })
    return {"rounds": rounds}


def tournament_record(user_id, number):
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT * FROM tournaments WHERE user_id=? AND number=?",
            (user_id, number),
        ).fetchone()
    return row


def start_tournament(user_id, number):
    item = TOURNAMENT_BY_NUM.get(number)
    if item is None:
        return None, "Турнир не найден"
    unlocked, opens_at = tournament_is_open(user_id, number)
    if not unlocked:
        return None, f"Турнир откроется через {days_left_text(opens_at)}"
    record = tournament_record(user_id, number)
    if record and record["status"] == "won":
        return record, "Турнир уже выигран"
    if record and record["status"] == "active":
        return record, None
    bracket = build_bracket(item)
    now = iso(now_utc())
    with closing(get_db()) as db:
        if record:
            db.execute(
                """UPDATE tournaments SET status='active', lives=?, current_round=0,
                bracket=?, won=0, updated_at=? WHERE id=?""",
                (item["lives"], json.dumps(bracket, ensure_ascii=False), now, record["id"]),
            )
            tid = record["id"]
        else:
            cursor = db.execute(
                """INSERT INTO tournaments
                (user_id, number, status, lives, current_round, bracket, won, created_at, updated_at)
                VALUES (?,?,'active',?,0,?,0,?,?)""",
                (user_id, number, item["lives"], json.dumps(bracket, ensure_ascii=False), now, now),
            )
            tid = cursor.lastrowid
        db.commit()
        row = db.execute("SELECT * FROM tournaments WHERE id=?", (tid,)).fetchone()
    return row, None


def create_tournament_game(row):
    item = TOURNAMENT_BY_NUM.get(row["number"])
    bracket = json.loads(row["bracket"])
    index = row["current_round"]
    if index >= len(bracket["rounds"]):
        return None, "Турнир завершён"
    match = bracket["rounds"][index]["player"]
    if match.get("result"):
        return None, "Партия уже сыграна"
    bot = bot_by_elo(match["bot_elo"])
    if bot["elo"] > 1000:
        bot = min(BOTS, key=lambda b: abs(b["elo"] - match["bot_elo"]))
    gid = create_game(
        row["user_id"], "tournament", bot, match["user_color"],
        random.choice(FULL_CONTROLS[:3]), row["number"], index + 1,
    )
    match["game_id"] = gid
    with closing(get_db()) as db:
        db.execute(
            "UPDATE tournaments SET bracket=?, updated_at=? WHERE id=?",
            (json.dumps(bracket, ensure_ascii=False), iso(now_utc()), row["id"]),
        )
        db.commit()
    return gid, None


def process_tournament_result(gid):
    row = load_game(gid)
    if row is None or not row["tournament_number"] or not row["user_id"]:
        return
    record = tournament_record(row["user_id"], row["tournament_number"])
    if record is None or record["status"] != "active":
        return
    bracket = json.loads(record["bracket"])
    index = record["current_round"]
    if index >= len(bracket["rounds"]):
        return
    match = bracket["rounds"][index]["player"]
    if match.get("game_id") != gid or match.get("result"):
        return
    item = TOURNAMENT_BY_NUM[row["tournament_number"]]
    match["result"] = row["result"]
    match["game_id"] = gid
    lives = record["lives"]
    status = "active"
    won = 0
    if row["result"] == "win":
        index += 1
        if index >= len(bracket["rounds"]):
            status = "won"
            won = 1
    else:
        lives -= 1
        if lives <= 0:
            status = "lost"
        else:
            new_opponent = pick_tournament_bot(item, {match.get("opponent")})
            match["opponent"] = new_opponent["name"]
            match["bot_elo"] = new_opponent["elo"]
            match["user_color"] = random.choice(["white", "black"])
            match["white"] = "Ты" if match["user_color"] == "white" else new_opponent["name"]
            match["black"] = new_opponent["name"] if match["user_color"] == "white" else "Ты"
            match["game_id"] = None
            match["result"] = None
    titles = None
    if status == "won":
        user = fetch_user(row["user_id"])
        if user:
            titles = json.loads(user["titles"] or "[]")
            if item["title"] not in titles:
                titles.append(item["title"])
            with closing(get_db()) as db:
                db.execute(
                    "UPDATE users SET cups=cups+1, titles=? WHERE id=?",
                    (json.dumps(titles, ensure_ascii=False), user["id"]),
                )
                db.commit()
    with closing(get_db()) as db:
        db.execute(
            "UPDATE tournaments SET status=?, lives=?, current_round=?, bracket=?, won=?, updated_at=? WHERE id=?",
            (status, lives, index, json.dumps(bracket, ensure_ascii=False), won, iso(now_utc()), record["id"]),
        )
        db.commit()


def fmt_eval(cp):
    if cp is None:
        return "0.00"
    if abs(cp) >= 9000:
        if cp > 0:
            return "Мат за тебя"
        return "Мат против тебя"
    return f"{cp / 100.0:+.2f}"


def eval_word(cp):
    if abs(cp) >= 9000:
        return "мат"
    if cp >= 300:
        return "выигрышная позиция"
    if cp >= 100:
        return "перевес"
    if cp >= -100:
        return "равная игра"
    if cp >= -300:
        return "хуже"
    return "проиграно"


COACH_STYLES = {
    "strict": {
        "open_bad": ["Стоп.", "Так не пойдёт.", "Разбираем без сантиментов."],
        "open_good": ["Верно.", "Принято.", "Дисциплинированно."],
        "close_bad": ["Считай варианты до конца.", "В следующей партии таких зевков быть не должно.",
                      "Концентрация решает."],
        "close_good": ["Держи концентрацию.", "Продолжай так же.", "Работай чисто."],
        "advice": ["Проверяй все шахи и взятия.", "Сначала считай форсированные варианты.",
                   "Не спеши с выводом."],
    },
    "calm": {
        "open_bad": ["Спокойно.", "Без паники.", "Есть над чем подумать."],
        "open_good": ["Хорошо.", "Спокойно и точно.", "Правильное решение."],
        "close_bad": ["Не торопись в следующий раз.", "Найди план и держи его.", "Ошибка — часть работы."],
        "close_good": ["Сохраняй план.", "Играй в своём темпе.", "Всё идёт правильно."],
        "advice": ["Смотри на позицию целиком.", "Сначала улучшай худшую фигуру.",
                   "Не меняй план без причины."],
    },
    "energetic": {
        "open_bad": ["Стоп-стоп!", "Так нельзя!", "Теряем темп!"],
        "open_good": ["Отлично!", "Вот это ход!", "Так держать!"],
        "close_bad": ["Соберись и считай!", "Верни инициативу!", "Не отдавай темп просто так!"],
        "close_good": ["Дави дальше!", "Не сбавляй!", "Продолжай в том же духе!"],
        "advice": ["Ищи тактику!", "Считай форсированные линии!", "Не бойся жертв!"],
    },
    "soft": {
        "open_bad": ["Ничего страшного.", "Бывает.", "Давай посмотрим спокойно."],
        "open_good": ["Молодец.", "Очень хорошо.", "Ты справляешься."],
        "close_bad": ["В следующий раз получится.", "Не ругай себя.", "Просто запомни этот мотив."],
        "close_good": ["Продолжай.", "Ты на верном пути.", "Так и держи."],
        "advice": ["Сначала проверь, не отдаёшь ли фигуру.", "Выдохни и посчитай.",
                   "Ищи простые защиты."],
    },
    "academic": {
        "open_bad": ["Обрати внимание.", "Здесь есть академическая проблема.", "Разберём строго."],
        "open_good": ["Корректно.", "Академически верно.", "Хорошее решение."],
        "close_bad": ["Смотри на структуру и слабые поля.", "Оценивай следствия до конца.",
                      "Считай не только свой план."],
        "close_good": ["Сохраняй структуру.", "Продолжай по плану.", "Развивай преимущество."],
        "advice": ["Сначала оцени пешечную структуру.", "Смотри на слабые поля.",
                   "Считай варианты до оценки."],
    },
    "confident": {
        "open_bad": ["Нет.", "Это ошибка.", "Так позицию не выиграть."],
        "open_good": ["Да.", "Точно.", "Уверенный ход."],
        "close_bad": ["Играй точнее.", "Не разбрасывай фигуры.", "Держи контроль."],
        "close_good": ["Так и играй.", "Держи преимущество.", "Не давай сопернику шансов."],
        "advice": ["Считай до конца.", "Проверь ответ соперника.", "Не играй на удачу."],
    },
    "fast": {
        "open_bad": ["Стоп.", "Потеря.", "Не тот ход."],
        "open_good": ["Быстро и точно.", "Хорошо.", "В темпе."],
        "close_bad": ["Считай форсированно.", "Проверь взятия.", "Не тормози с защитой."],
        "close_good": ["Дави в темпе.", "Не снижай скорость.", "Продолжай."],
        "advice": ["Считай шахи и взятия.", "Ищи форсированный вариант.", "Не трать темп."],
    },
    "thoughtful": {
        "open_bad": ["Есть нюанс.", "Не всё так просто.", "Позиция требует внимания."],
        "open_good": ["Тонко.", "Верное чувство позиции.", "Хороший план."],
        "close_bad": ["Подумай о плане соперника.", "Оцени слабые поля.",
                      "Не меняй структуру вслепую."],
        "close_good": ["Развивай план.", "Следи за пешками.", "Сохраняй координацию."],
        "advice": ["Смотри на пешечную структуру.", "Улучшай худшую фигуру.",
                   "Думай о плане, а не о ходе."],
    },
    "friendly": {
        "open_bad": ["Давай разберём.", "Ничего, это опыт.", "Смотри, что случилось."],
        "open_good": ["Отлично!", "Ты молодец.", "Хороший ход."],
        "close_bad": ["В следующий раз заметишь.", "Запомни этот мотив.", "Всё получится."],
        "close_good": ["Продолжай!", "Ты справляешься.", "Так держать."],
        "advice": ["Проверяй, какие фигуры под боем.", "Считай хотя бы на два хода.",
                   "Не бойся задавать вопросы к позиции."],
    },
    "mentor": {
        "open_bad": ["Смотри.", "Запомни этот момент.", "Здесь был урок."],
        "open_good": ["Верно.", "Это зрелый ход.", "Так и надо."],
        "close_bad": ["Опыт приходит с разбором.", "В следующий раз увидишь раньше.",
                      "Держи голову холодной."],
        "close_good": ["Продолжай расти.", "Держи уровень.", "Играй с достоинством."],
        "advice": ["Сначала безопасность короля.", "Потом активность фигур.",
                   "Не теряй нить плана."],
    },
}


COACH_FAMILY = {
    "strict": "analytical", "academic": "analytical", "confident": "analytical",
    "fast": "analytical", "calm": "supportive", "soft": "supportive",
    "friendly": "supportive", "energetic": "energetic", "mentor": "energetic",
    "thoughtful": "thoughtful",
}
PHASE_RU = {
    "opening": "в дебюте",
    "middlegame": "в миттельшпиле",
    "endgame": "в эндшпиле",
}
SPECIAL_OPENERS = {
    "strict": "Красиво.",
    "calm": "Впечатляет.",
    "energetic": "Вот это да!",
    "soft": "Как красиво.",
    "academic": "Изящно.",
    "confident": "Сильно.",
    "fast": "Красиво!",
    "thoughtful": "Тонко.",
    "friendly": "Здорово!",
    "mentor": "Мастерски.",
}


def coach_text(info, style="strict"):
    st = COACH_STYLES.get(style, COACH_STYLES["strict"])
    label = info.get("label", "best")
    san = info.get("san", "")
    best = info.get("best_san") or san
    loss = int(info.get("loss") or 0)
    before = info.get("before", 0)
    after = info.get("after", 0)
    to_sq = info.get("to", "")
    from_sq = info.get("from", "")
    piece_type = info.get("piece_type")
    captured_type = info.get("captured_type")
    piece_nom = PIECE_NOM.get(piece_type, "фигура")
    piece_gen = PIECE_GEN.get(piece_type, "фигуры")
    piece_acc = PIECE_ACC.get(piece_type, "фигуру")
    captured_acc = PIECE_ACC.get(captured_type, "") if captured_type else ""
    sacrifice = bool(info.get("sacrifice"))
    is_capture = bool(info.get("is_capture"))
    is_user = bool(info.get("is_user_move", True))
    ply = int(info.get("ply") or 0)
    bad = label in ("blunder", "mistake", "inaccuracy", "miss")
    family = COACH_FAMILY.get(style, "analytical")
    phase = PHASE_RU.get(info.get("phase"), "в этой позиции")
    rng = random.Random(101 + ply * 37 + sum(ord(ch) for ch in (style + san + label)))
    if label in ("brilliant", "amethyst", "ideal"):
        parts = [SPECIAL_OPENERS.get(style, "Красиво.")]
    else:
        parts = [rng.choice(st["open_bad"] if bad else st["open_good"])]
    if label == "forced":
        parts.append(f"Единственный законный ход — {san}; оценка {fmt_eval(after)}.")
    elif label == "book":
        parts.append(f"{san} — дебютная теория, позиция идёт по известной схеме; "
                     f"оценка {fmt_eval(after)}.")
    elif label == "amethyst":
        who = "Ты жертвуешь" if is_user else "Соперник жертвует"
        reply = "ответа соперника" if is_user else "твоего ответа"
        parts.append(f"{who} {PIECE_INSTR.get(piece_type, 'фигурой')} на {to_sq}: после любого "
                     f"{reply} следует мат в 1 ход. {san} — аметистовый ход. "
                     f"Такое видят немногие.")
    elif label == "brilliant":
        who = "Ты жертвуешь" if is_user else "Соперник жертвует"
        if is_user:
            parts.append(f"{who} {PIECE_INSTR.get(piece_type, 'фигурой')} на {to_sq}, и движок "
                         f"видит форсированный мат в 2+ хода: после {san} оценка "
                         f"{fmt_eval(after)}. Риск посчитан.")
        else:
            parts.append(f"{who} {PIECE_INSTR.get(piece_type, 'фигурой')} на {to_sq} и форсирует "
                         f"мат в 2+ хода. Позиция требует точной защиты.")
    elif label == "ideal":
        if is_user:
            parts.append(f"{san} — идеальный ход: создана угроза мата в 1 ход. "
                         f"Ошибка соперника — и мат; оценка {fmt_eval(after)}.")
        else:
            parts.append(f"Соперник сыграл {san} и создал угрозу мата в 1 ход. "
                         f"Ошибка — и мат; оценка {fmt_eval(after)}.")
    elif label == "miss":
        parts.append(f"До хода был перевес {fmt_eval(before)}, а {san} оставляет "
                     f"{fmt_eval(after)}; {best} вёл к победе.")
    elif label == "great":
        parts.append(f"{san} — единственный ход, который держит {fmt_eval(after)}; "
                     f"альтернативы теряли.")
    elif label == "best":
        parts.append(f"{san} — лучший ход; {piece_nom} с {from_sq} на {to_sq} сохраняет "
                     f"{fmt_eval(after)}.")
    elif label == "excellent":
        parts.append(f"{san} почти не уступает лучшему: потеря {loss} cp, оценка "
                     f"{fmt_eval(after)}.")
    elif label == "good":
        parts.append(f"{san} надёжен: потеря {loss} cp, оценка {fmt_eval(after)}.")
    else:
        if family == "supportive":
            if sacrifice:
                parts.append(f"После {san} {piece_acc} на {to_sq} можно забрать — теряется "
                             f"{loss} cp, оценка с {fmt_eval(before)} до {fmt_eval(after)}.")
            elif is_capture and captured_acc:
                parts.append(f"Взятие {captured_acc} на {to_sq} не компенсирует потерю: "
                             f"{loss} cp, оценка с {fmt_eval(before)} до {fmt_eval(after)}.")
            else:
                parts.append(f"Ход {san} стоит {loss} cp: оценка меняется с "
                             f"{fmt_eval(before)} до {fmt_eval(after)}.")
        elif family == "energetic":
            if sacrifice:
                parts.append(f"{san} отдаёт {piece_acc} на {to_sq}! Минус {loss} cp, "
                             f"оценка с {fmt_eval(before)} до {fmt_eval(after)}.")
            else:
                parts.append(f"{san} — потеря {loss} cp! Оценка с {fmt_eval(before)} "
                             f"до {fmt_eval(after)}.")
        elif family == "thoughtful":
            if sacrifice:
                parts.append(f"После {san} {piece_nom} на {to_sq} теряет опору: {loss} cp, "
                             f"оценка с {fmt_eval(before)} до {fmt_eval(after)}; {phase} это "
                             f"особенно важно.")
            else:
                parts.append(f"Ход {san} меняет рисунок позиции: {loss} cp, оценка с "
                             f"{fmt_eval(before)} до {fmt_eval(after)}.")
        else:
            if sacrifice:
                parts.append(f"Ход {san} отдаёт {piece_acc} на {to_sq}: потеря {loss} cp, "
                             f"оценка с {fmt_eval(before)} до {fmt_eval(after)}.")
            elif is_capture and captured_acc:
                parts.append(f"Взятие {captured_acc} на {to_sq} не спасает: потеря {loss} cp, "
                             f"оценка с {fmt_eval(before)} до {fmt_eval(after)}.")
            else:
                parts.append(f"После {san} потеря {loss} cp: оценка с {fmt_eval(before)} "
                             f"до {fmt_eval(after)}.")
        if best != san:
            if family == "supportive":
                parts.append(f"В следующий раз попробуй {best} — он держал {fmt_eval(before)}.")
            elif family == "energetic":
                parts.append(f"Нужен был {best}! Он держал {fmt_eval(before)}.")
            else:
                parts.append(f"Корректно было {best}: он держал {fmt_eval(before)}.")
    if not bad and best != san and label not in ("book", "forced"):
        parts.append(f"Движок предлагал {best}.")
    if label in ("best", "great", "book", "forced"):
        parts.append("Это совпадает с выбором движка.")
    parts.append(rng.choice(st["advice"]))
    parts.append(rng.choice(st["close_bad"] if bad else st["close_good"]))
    if label in ("brilliant", "amethyst", "ideal"):
        parts.append("Запомни этот мотив: он пригодится в похожих позициях.")
    return " ".join(parts)


def trainer_text(info):
    return coach_text(info, "strict")


def analyse_game(gid, force=False):
    row = load_game(gid)
    if row is None:
        return None
    if row["analysis"] and not force:
        try:
            return json.loads(row["analysis"])
        except (TypeError, ValueError):
            pass
    moves = game_moves(row)
    try:
        start_fen = row["start_fen"]
    except (IndexError, KeyError):
        start_fen = None
    try:
        start_board = chess.Board(start_fen) if start_fen else chess.Board()
    except ValueError:
        start_board = chess.Board()
    boards = [start_board]
    board = start_board.copy()
    for item in moves:
        try:
            board.push(chess.Move.from_uci(item["uci"]))
        except ValueError:
            break
        boards.append(board.copy())
    if len(boards) != len(moves) + 1:
        moves = moves[:len(boards) - 1]
    use_engine = ENGINE.available()
    depth = 12
    evals = []
    for position in boards:
        if use_engine:
            evals.append(engine_eval(position, depth=depth))
        else:
            best_move, score = fallback_search(position, 1)
            evals.append({"cp": score, "best": best_move, "second_cp": score, "mate": None})
    infos = []
    for index, move in enumerate(moves):
        position = boards[index]
        before = evals[index]["cp"]
        after = -evals[index + 1]["cp"]
        loss = max(0, before - after)
        actual = position.parse_uci(move["uci"]) if hasattr(position, "parse_uci") else chess.Move.from_uci(move["uci"])
        piece = position.piece_at(actual.from_square)
        piece_type = piece.piece_type if piece else None
        captured = position.piece_at(actual.to_square)
        best_move = evals[index].get("best")
        best_san = ""
        if best_move is not None:
            try:
                if best_move in position.legal_moves:
                    best_san = position.san(best_move)
            except Exception:
                best_san = ""
        second = evals[index].get("second_cp", before)
        label, flags = classify_position(position, actual, before, after, best_move, second, index)
        loss = flags["loss"]
        gap = flags["gap"]
        sacrifice = flags["sacrifice"]
        only_saving = flags["only_saving"]
        material = sum(
            VALUES[item.piece_type] for item in position.piece_map().values()
            if item.piece_type != chess.KING
        )
        has_queen = any(item.piece_type == chess.QUEEN for item in position.piece_map().values())
        if index < 10:
            phase = "opening"
        elif material < 2600 or not has_queen:
            phase = "endgame"
        else:
            phase = "middlegame"
        info = {
            "ply": index,
            "san": move["san"],
            "uci": move["uci"],
            "color": move["color"],
            "from": chess.square_name(actual.from_square),
            "to": chess.square_name(actual.to_square),
            "piece_type": piece_type,
            "captured_type": captured.piece_type if captured else None,
            "is_capture": captured is not None,
            "is_check": boards[index + 1].is_check(),
            "is_castle": position.is_castling(actual),
            "is_promotion": actual.promotion is not None,
            "phase": phase,
            "label": label,
            "loss": int(loss),
            "before": int(before),
            "after": int(after),
            "second_cp": int(second) if second is not None else int(before),
            "gap": int(gap),
            "only_saving": bool(only_saving),
            "mate_in_one": bool(flags.get("mate_in_one")),
            "forced_mate": bool(flags.get("forced_mate")),
            "mate_threat": bool(flags.get("mate_threat")),
            "sacrifice": bool(sacrifice),
            "eval_white": before if move["color"] == "white" else -before,
            "eval_white_before": before if move["color"] == "white" else -before,
            "eval_white_after": after if move["color"] == "white" else -after,
            "mate": evals[index].get("mate"),
        }
        info["text"] = coach_text(info, "strict")
        infos.append(info)
    user_color = row["user_color"] or "white"
    if row["user_id"] is None:
        name_parts = (row["bot_name"] or "").split(" - ", 1)
        white_name = name_parts[0] if name_parts else "Белые"
        black_name = name_parts[1] if len(name_parts) > 1 else "Чёрные"
    else:
        white_name = "Ты" if user_color == "white" else (row["bot_name"] or "Соперник")
        black_name = "Ты" if user_color == "black" else (row["bot_name"] or "Соперник")
    counts = {"user": {}, "bot": {}}
    losses = {"user": [], "bot": []}
    for info in infos:
        side = "user" if info["color"] == user_color else "bot"
        counts[side][info["label"]] = counts[side].get(info["label"], 0) + 1
        losses[side].append(min(info["loss"], 1000))
    accuracy = {}
    for side in ("user", "bot"):
        if losses[side]:
            values = [
                100.0 * math.exp(-min(loss, 1000) / 300.0)
                for loss in losses[side]
            ]
            accuracy[side] = round(max(0.0, min(100.0, sum(values) / len(values))), 1)
        else:
            accuracy[side] = 0.0
    result = {
        "game_id": gid,
        "user_color": user_color,
        "is_bot_game": row["user_id"] is None,
        "white_name": white_name,
        "black_name": black_name,
        "moves": infos,
        "counts": counts,
        "accuracy": accuracy,
        "result": row["result"],
        "reason": row["reason"],
        "bot_name": row["bot_name"],
        "bot_elo": row["bot_elo"],
        "engine": "stockfish" if use_engine else "fallback",
        "final_eval": infos[-1]["after"] if infos else 0,
        "fens": [position.fen() for position in boards],
        "pgn": row["pgn"],
    }
    with closing(get_db()) as db:
        db.execute("UPDATE games SET analysis=? WHERE id=?", (json.dumps(result, ensure_ascii=False), gid))
        db.commit()
    return result


def user_games(user_id, limit=40):
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT * FROM games WHERE user_id=? AND mode!='tournament_bot' ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return rows


def profile_stats(user_id):
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT result, mode FROM games WHERE user_id=? AND status='finished'",
            (user_id,),
        ).fetchall()
        won = db.execute(
            "SELECT number FROM tournaments WHERE user_id=? AND status='won' ORDER BY number",
            (user_id,),
        ).fetchall()
        active = db.execute(
            "SELECT number, lives, current_round, status FROM tournaments WHERE user_id=? ORDER BY number",
            (user_id,),
        ).fetchall()
    wins = sum(1 for row in rows if row["result"] == "win")
    losses = sum(1 for row in rows if row["result"] == "loss")
    draws = sum(1 for row in rows if row["result"] == "draw")
    return {
        "total": len(rows),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "tournaments_won": [row["number"] for row in won],
        "tournaments": [dict(row) for row in active],
    }


RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ACCOUNT_FORMAT = "chessamy-account"
ACCOUNT_VERSION = 1


def normalize_recovery(code):
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def make_recovery_code():
    groups = [
        "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4))
        for _ in range(3)
    ]
    return "AMY-" + "-".join(groups)


def row_value(row, key, default=None):
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def register_user(username, password):
    error = validate_username(username)
    if error:
        return None, error, None
    error = validate_password(password)
    if error:
        return None, error, None
    username = username.strip()
    recovery_code = make_recovery_code()
    with closing(get_db()) as db:
        exists = db.execute(
            "SELECT id FROM users WHERE username_lower=?", (username.lower(),)
        ).fetchone()
        if exists:
            return None, "Этот ник уже занят", None
        token = secrets.token_urlsafe(32)
        cursor = db.execute(
            """INSERT INTO users (username, username_lower, password_hash, elo, cups, titles,
            remember_token, recovery_hash, created_at) VALUES (?,?,?,500,0,'[]',?,?,?)""",
            (
                username,
                username.lower(),
                generate_password_hash(password),
                token,
                generate_password_hash(normalize_recovery(recovery_code)),
                iso(now_utc()),
            ),
        )
        uid = cursor.lastrowid
        init_tournament_access(db, uid)
        db.commit()
    return fetch_user(uid), None, recovery_code


def json_error(message, code=400):
    return jsonify({"ok": False, "error": message}), code


def require_user():
    user = current_user()
    if user is None:
        return None
    return user


def remember_user_from_cookie():
    token = request.cookies.get("chessamy_remember")
    if not token:
        return None
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT * FROM users WHERE remember_token=?", (token,)
        ).fetchone()
    return row


@app.route("/")
def index():
    user = current_user()
    remember = None
    if user is None:
        remember = remember_user_from_cookie()
    return render_template(
        "index.html",
        remember_name=remember["username"] if remember else None,
        need_account=request.args.get("need_account") == "1",
    )


COACH_REQUIRED_ENDPOINTS = {
    "menu", "games_page", "online_page", "tournaments_page",
    "game_page", "analysis_page", "profile_page", "tournament_page", "backups_page",
}


@app.before_request
def enforce_coach_choice():
    if request.endpoint not in COACH_REQUIRED_ENDPOINTS:
        return None
    user = current_user()
    if user is None:
        return None
    try:
        coach_id = user["coach_id"]
    except (IndexError, KeyError):
        coach_id = None
    if not coach_id:
        return redirect(url_for("coach_page"))
    return None


@app.route("/coach")
def coach_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    try:
        coach_id = user["coach_id"]
    except (IndexError, KeyError):
        coach_id = None
    return render_template(
        "coach.html", selected=coach_for_user(user), locked=bool(coach_id)
    )


@app.route("/api/coach/select", methods=["POST"])
def api_coach_select():
    user = current_user()
    if user is None:
        return json_error("Для выбора тренера нужен аккаунт", 401)
    try:
        existing = user["coach_id"]
    except (IndexError, KeyError):
        existing = None
    if existing:
        return json_error("Тренер уже выбран и не меняется", 403)
    data = request.get_json(silent=True) or {}
    try:
        coach_id = int(data.get("coach_id"))
    except (TypeError, ValueError):
        return json_error("Выбери тренера")
    coach = COACH_BY_ID.get(coach_id)
    if coach is None:
        return json_error("Тренер не найден", 404)
    with closing(get_db()) as db:
        db.execute("UPDATE users SET coach_id=? WHERE id=?", (coach_id, user["id"]))
        db.commit()
    return jsonify({
        "ok": True,
        "redirect": url_for("menu"),
        "coach": coach,
    })


@app.route("/menu")
def menu():
    return render_template("menu.html", view="menu")


@app.route("/games")
def games_page():
    return render_template(
        "menu.html", view="games", bots=BOTS, fast_bot=FAST_BOT,
        controls=FAST_CONTROLS + FULL_CONTROLS,
    )


@app.route("/online")
def online_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    low, high = online_elo_bounds(user["elo"])
    return render_template(
        "menu.html", view="online", bots=online_bots_for(user["elo"]),
        fast_bot=None, controls=FAST_CONTROLS + FULL_CONTROLS,
        user_elo=user["elo"], elo_low=low, elo_high=high,
    )


@app.route("/tournaments")
def tournaments_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    return render_template(
        "menu.html", view="tournaments", tournaments=tournament_info_for_user(user)
    )


@app.route("/game/<int:gid>")
def game_page(gid):
    row = load_game(gid)
    if row is None:
        return redirect(url_for("menu"))
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return redirect(url_for("menu"))
    return render_template("game.html", game_id=gid, game=row)


@app.route("/analysis/<int:gid>")
def analysis_page(gid):
    row = load_game(gid)
    if row is None:
        return redirect(url_for("menu"))
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return redirect(url_for("menu"))
    return render_template("analysis.html", game_id=gid, game=row)


@app.route("/profile")
def profile_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    stats = profile_stats(user["id"])
    titles = json.loads(user["titles"] or "[]")
    tournaments = tournament_info_for_user(user)
    cups = [item for item in tournaments if item["won"]]
    return render_template(
        "profile.html", profile=user, stats=stats, titles=titles,
        tournaments=tournaments, cups=cups, coach=coach_for_user(user),
        recent_games=user_games(user["id"], 12),
    )


@app.route("/tournament/<int:num>")
def tournament_page(num):
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    item = TOURNAMENT_BY_NUM.get(num)
    if item is None:
        return redirect(url_for("tournaments_page"))
    record = tournament_record(user["id"], num)
    bracket = json.loads(record["bracket"]) if record else None
    unlocked, opens_at = tournament_is_open(user["id"], num)
    next_tournament = None
    if record and record["status"] == "won" and (num + 1) in TOURNAMENT_BY_NUM:
        next_item = TOURNAMENT_BY_NUM[num + 1]
        next_opens = access_map(user["id"]).get(num + 1)
        next_tournament = {
            "num": num + 1,
            "name": next_item["name"],
            "left": days_left_text(next_opens),
        }
    return render_template(
        "tournament.html", item=item, record=record, bracket=bracket,
        unlocked=unlocked, opens_at=opens_at,
        left=days_left_text(opens_at) if opens_at else "открыт",
        next_tournament=next_tournament,
    )


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user, error, recovery_code = register_user(username, password)
    if error:
        return json_error(error)
    session["uid"] = user["id"]
    session.pop("guest", None)
    response = jsonify({
        "ok": True,
        "user": user_json(user),
        "recovery_code": recovery_code,
        "redirect": url_for("coach_page"),
    })
    if data.get("remember"):
        response.set_cookie(
            "chessamy_remember", user["remember_token"], max_age=315360000,
            httponly=True, samesite="Lax",
        )
    return response


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return json_error("Введи ник и пароль")
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT * FROM users WHERE username_lower=?", (username.lower(),)
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return json_error("Неверный ник или пароль")
    session["uid"] = row["id"]
    session.pop("guest", None)
    try:
        coach_id = row["coach_id"]
    except (IndexError, KeyError):
        coach_id = None
    response = jsonify({
        "ok": True,
        "user": user_json(row),
        "redirect": url_for("menu") if coach_id else url_for("coach_page"),
    })
    if data.get("remember"):
        response.set_cookie(
            "chessamy_remember", row["remember_token"], max_age=315360000,
            httponly=True, samesite="Lax",
        )
    return response


@app.route("/api/remember", methods=["POST"])
def api_remember():
    row = remember_user_from_cookie()
    if row is None:
        return json_error("Сохранённый вход не найден", 401)
    session["uid"] = row["id"]
    session.pop("guest", None)
    try:
        coach_id = row["coach_id"]
    except (IndexError, KeyError):
        coach_id = None
    return jsonify({
        "ok": True,
        "redirect": url_for("menu") if coach_id else url_for("coach_page"),
    })


@app.route("/api/forget", methods=["POST"])
def api_forget():
    row = remember_user_from_cookie()
    if row:
        with closing(get_db()) as db:
            db.execute("UPDATE users SET remember_token=NULL WHERE id=?", (row["id"],))
            db.commit()
    response = jsonify({"ok": True})
    response.delete_cookie("chessamy_remember")
    return response


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    response = jsonify({"ok": True, "redirect": url_for("index")})
    response.delete_cookie("chessamy_remember")
    return response


@app.route("/api/password/recover", methods=["POST"])
def api_password_recover():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    code = normalize_recovery(data.get("code"))
    password = data.get("new_password") or ""
    if not username or not code or not password:
        return json_error("Заполни ник, код восстановления и новый пароль")
    error = validate_password(password)
    if error:
        return json_error(error)
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT * FROM users WHERE username_lower=?", (username.lower(),)
        ).fetchone()
        if row is None:
            return json_error("Аккаунт с таким ником не найден", 404)
        stored = row_value(row, "recovery_hash")
        if not stored or not check_password_hash(stored, code):
            return json_error("Код восстановления не подходит")
        fresh_code = make_recovery_code()
        db.execute(
            "UPDATE users SET password_hash=?, recovery_hash=?, remember_token=NULL WHERE id=?",
            (
                generate_password_hash(password),
                generate_password_hash(normalize_recovery(fresh_code)),
                row["id"],
            ),
        )
        db.commit()
    session["uid"] = row["id"]
    session.pop("guest", None)
    user = fetch_user(row["id"])
    response = jsonify({
        "ok": True,
        "user": user_json(user),
        "recovery_code": fresh_code,
        "redirect": url_for("menu") if row_value(row, "coach_id") else url_for("coach_page"),
    })
    response.delete_cookie("chessamy_remember")
    return response


@app.route("/api/password/change", methods=["POST"])
def api_password_change():
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    data = request.get_json(silent=True) or {}
    current = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if not check_password_hash(user["password_hash"], current):
        return json_error("Текущий пароль не подходит")
    error = validate_password(new_password)
    if error:
        return json_error(error)
    if check_password_hash(user["password_hash"], new_password):
        return json_error("Новый пароль совпадает с текущим")
    with closing(get_db()) as db:
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), user["id"]),
        )
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/recovery/code", methods=["POST"])
def api_recovery_code():
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    code = make_recovery_code()
    with closing(get_db()) as db:
        db.execute(
            "UPDATE users SET recovery_hash=? WHERE id=?",
            (generate_password_hash(normalize_recovery(code)), user["id"]),
        )
        db.commit()
    return jsonify({"ok": True, "recovery_code": code})


def account_payload(user):
    uid = user["id"]
    with closing(get_db()) as db:
        games = db.execute(
            "SELECT * FROM games WHERE user_id=? ORDER BY id", (uid,)
        ).fetchall()
        tournaments = db.execute(
            "SELECT * FROM tournaments WHERE user_id=? ORDER BY number", (uid,)
        ).fetchall()
        access = db.execute(
            "SELECT * FROM tournament_access WHERE user_id=? ORDER BY number", (uid,)
        ).fetchall()
    try:
        titles = json.loads(user["titles"])
    except (TypeError, ValueError):
        titles = []
    return {
        "app": ACCOUNT_FORMAT,
        "version": ACCOUNT_VERSION,
        "exported_at": iso(now_utc()),
        "profile": {
            "username": user["username"],
            "elo": user["elo"],
            "cups": user["cups"],
            "titles": titles,
            "coach_id": row_value(user, "coach_id"),
            "created_at": user["created_at"],
        },
        "games": [dict(row) for row in games],
        "tournaments": [dict(row) for row in tournaments],
        "tournament_access": [dict(row) for row in access],
    }


GAME_IMPORT_FIELDS = (
    "mode", "bot_name", "bot_elo", "user_color", "time_control", "pgn", "moves",
    "result", "reason", "analysis", "tournament_number", "round_number",
    "white_ms", "black_ms", "last_ts", "clock_active", "timed", "status",
    "created_at", "finished_at",
)


def import_account_data(uid, payload, mode="merge"):
    stats = {"games": 0, "tournaments": 0, "access": 0, "elo": False}
    games = payload.get("games") if isinstance(payload.get("games"), list) else []
    tournaments = payload.get("tournaments") if isinstance(payload.get("tournaments"), list) else []
    access = payload.get("tournament_access") if isinstance(payload.get("tournament_access"), list) else []
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    with closing(get_db()) as db:
        existing = {
            (row["created_at"], row["pgn"])
            for row in db.execute(
                "SELECT created_at, pgn FROM games WHERE user_id=?", (uid,)
            )
        }
        for item in games[:20000]:
            if not isinstance(item, dict):
                continue
            if (item.get("status") or "finished") == "active":
                continue
            key = (item.get("created_at"), item.get("pgn") or "")
            if key in existing:
                continue
            values = {field: item.get(field) for field in GAME_IMPORT_FIELDS}
            if not values.get("mode"):
                continue
            if values.get("timed") is None:
                values["timed"] = 1
            if values.get("status") is None:
                values["status"] = "finished"
            if not values.get("created_at"):
                values["created_at"] = iso(now_utc())
            columns = ", ".join(["user_id"] + list(GAME_IMPORT_FIELDS))
            placeholders = ", ".join(["?"] * (len(GAME_IMPORT_FIELDS) + 1))
            try:
                db.execute(
                    f"INSERT INTO games ({columns}) VALUES ({placeholders})",
                    [uid] + [values[field] for field in GAME_IMPORT_FIELDS],
                )
            except sqlite3.Error:
                continue
            existing.add(key)
            stats["games"] += 1
        for item in tournaments[:200]:
            if not isinstance(item, dict) or not item.get("number"):
                continue
            cursor = db.execute(
                """INSERT OR IGNORE INTO tournaments (user_id, number, status, lives,
                current_round, bracket, won, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    uid,
                    int(item.get("number")),
                    item.get("status") or "active",
                    int(item.get("lives") or 0),
                    int(item.get("current_round") or 0),
                    item.get("bracket") or "{}",
                    1 if item.get("won") else 0,
                    item.get("created_at") or iso(now_utc()),
                    item.get("updated_at") or iso(now_utc()),
                ),
            )
            if cursor.rowcount:
                stats["tournaments"] += 1
        for item in access[:200]:
            if not isinstance(item, dict) or not item.get("number"):
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO tournament_access (user_id, number, opens_at) VALUES (?,?,?)",
                (uid, int(item.get("number")), item.get("opens_at") or iso(now_utc())),
            )
            if cursor.rowcount:
                stats["access"] += 1
        if profile:
            current = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if mode == "new":
                titles = profile.get("titles") if isinstance(profile.get("titles"), list) else []
                db.execute(
                    "UPDATE users SET elo=?, cups=?, titles=?, coach_id=? WHERE id=?",
                    (
                        max(100, min(4000, int(profile.get("elo") or 500))),
                        max(0, int(profile.get("cups") or 0)),
                        json.dumps(titles, ensure_ascii=False),
                        profile.get("coach_id"),
                        uid,
                    ),
                )
                stats["elo"] = True
            else:
                elo = max(int(current["elo"] or 0), int(profile.get("elo") or 0))
                cups = max(int(current["cups"] or 0), int(profile.get("cups") or 0))
                try:
                    current_titles = json.loads(current["titles"])
                except (TypeError, ValueError):
                    current_titles = []
                merged_titles = list(current_titles)
                for title in profile.get("titles") or []:
                    if title not in merged_titles:
                        merged_titles.append(title)
                if (
                    elo != current["elo"]
                    or cups != current["cups"]
                    or merged_titles != current_titles
                ):
                    db.execute(
                        "UPDATE users SET elo=?, cups=?, titles=? WHERE id=?",
                        (elo, cups, json.dumps(merged_titles, ensure_ascii=False), uid),
                    )
                    stats["elo"] = True
        db.commit()
    return stats


@app.route("/api/account/export")
def api_account_export():
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    payload = account_payload(user)
    blob = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    name = f"chessamy-{payload['profile']['username']}-{datetime.now().strftime('%Y%m%d')}.json"
    return send_file(
        io.BytesIO(blob),
        mimetype="application/json",
        as_attachment=True,
        download_name=name,
    )


@app.route("/api/account/import", methods=["POST"])
def api_account_import():
    data = request.get_json(silent=True) or {}
    payload = data.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return json_error("Файл повреждён: это не JSON")
    if not isinstance(payload, dict):
        return json_error("Не вижу данных аккаунта в файле")
    if not isinstance(payload.get("games"), list) and not isinstance(payload.get("profile"), dict):
        return json_error("В файле нет ни профиля, ни партий")
    user = current_user()
    recovery_code = None
    if user is None:
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        username = (data.get("username") or profile.get("username") or "").strip()
        password = data.get("password") or ""
        user, error, recovery_code = register_user(username, password)
        if error:
            return json_error(error)
        session["uid"] = user["id"]
        session.pop("guest", None)
        mode = "new"
    else:
        mode = "merge"
    stats = import_account_data(user["id"], payload, mode=mode)
    fresh = fetch_user(user["id"])
    return jsonify({
        "ok": True,
        "mode": mode,
        "imported": stats,
        "user": user_json(fresh),
        "recovery_code": recovery_code,
        "redirect": url_for("profile_page"),
    })


@app.route("/api/skip", methods=["POST"])
def api_skip():
    session.clear()
    session["guest"] = True
    return jsonify({"ok": True, "redirect": url_for("menu")})


@app.route("/api/me")
def api_me():
    user = current_user()
    return jsonify({
        "ok": True,
        "user": user_json(user),
        "guest": bool(session.get("guest")) and user is None,
    })


@app.route("/api/engine")
def api_engine():
    return jsonify({
        "ok": True,
        "stockfish": bool(STOCKFISH_PATH),
        "path": STOCKFISH_PATH or "",
    })


def color_to_play(value):
    if value == "random":
        return random.choice(["white", "black"])
    if value in ("white", "black"):
        return value
    return "white"


@app.route("/api/game/start", methods=["POST"])
def api_game_start():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode") or "games"
    if mode not in ("games", "online"):
        return json_error("Неизвестный режим")
    user = current_user()
    if mode == "online" and user is None:
        return json_error("Для игры на Эло нужен аккаунт", 401)
    try:
        bot_elo = int(data.get("bot_elo"))
    except (TypeError, ValueError):
        return json_error("Выбери бота")
    tc = data.get("time_control") or "10+0"
    if tc not in FAST_CONTROLS + FULL_CONTROLS:
        return json_error("Неизвестный контроль времени")
    if mode == "online":
        low, high = online_elo_bounds(user["elo"])
        if bot_elo < low or bot_elo > high:
            return json_error(f"Соперник должен быть в диапазоне {low}–{high} Эло")
        raw_name = str(data.get("bot_name") or "")
        name = re.sub(r"[^\w\s\-\.]", "", raw_name, flags=re.UNICODE)
        name = re.sub(r"\s+", " ", name).strip()[:32]
        bot = make_online_bot(bot_elo, name or random_online_name())
    elif bot_elo == 1:
        bot = FAST_BOT
        if tc not in FAST_CONTROLS:
            return json_error("Быстрая модель играет только контроли 1+0, 2+1, 3+0, 3+2, 5+0")
    else:
        bot = next((item for item in BOTS if item["elo"] == bot_elo), None)
        if bot is None:
            return json_error("Такого бота нет")
        if tc not in FULL_CONTROLS:
            return json_error("Уровни Stockfish играют только контроли 5+3, 10+0, 10+5, 15+10, 30+0")
    color = color_to_play(data.get("color"))
    start_fen = None
    raw_fen = (data.get("fen") or "").strip()
    if raw_fen:
        if mode != "games":
            return json_error("Позиция из FEN доступна в обычных играх")
        try:
            probe = chess.Board(raw_fen)
        except ValueError:
            return json_error("Не удалось разобрать FEN")
        if probe.king(chess.WHITE) is None or probe.king(chess.BLACK) is None:
            return json_error("На доске должны быть оба короля")
        if probe.is_game_over():
            return json_error("Позиция уже завершена")
        start_fen = probe.fen()
        color = "white" if probe.turn == chess.WHITE else "black"
    uid = user["id"] if user else None
    gid = create_game(uid, mode, bot, color, tc, start_fen=start_fen)
    return jsonify({"ok": True, "game_id": gid})


@app.route("/api/game/<int:gid>/state")
def api_game_state(gid):
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    state = game_state(row)
    return jsonify({"ok": True, "state": state})


@app.route("/api/game/move", methods=["POST"])
def api_game_move():
    data = request.get_json(silent=True) or {}
    try:
        gid = int(data.get("game_id"))
    except (TypeError, ValueError):
        return json_error("Нет game_id")
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    from_sq = (data.get("from") or "").lower()
    to_sq = (data.get("to") or "").lower()
    promotion = (data.get("promotion") or "").lower() or None
    if not re.fullmatch(r"[a-h][1-8]", from_sq) or not re.fullmatch(r"[a-h][1-8]", to_sq):
        return json_error("Некорректные клетки")
    row, error = apply_user_move(gid, from_sq, to_sq, promotion)
    if error:
        return json_error(error)
    return jsonify({"ok": True, "state": game_state(row)})


@app.route("/api/game/resign", methods=["POST"])
def api_game_resign():
    data = request.get_json(silent=True) or {}
    try:
        gid = int(data.get("game_id"))
    except (TypeError, ValueError):
        return json_error("Нет game_id")
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    if row["status"] == "active":
        row = finish_game(gid, "loss", "resign")
    return jsonify({"ok": True, "state": game_state(row)})


@app.route("/api/game/draw", methods=["POST"])
def api_game_draw():
    data = request.get_json(silent=True) or {}
    try:
        gid = int(data.get("game_id"))
    except (TypeError, ValueError):
        return json_error("Нет game_id")
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    if row["status"] != "active":
        return jsonify({"ok": True, "accepted": False, "state": game_state(row)})
    moves = game_moves(row)
    board = board_from_moves(moves, row["start_fen"])
    if row["bot_elo"] == 1:
        bot_eval = static_eval(board) if board.turn == chess.BLACK else -static_eval(board)
        bot_eval = -bot_eval
    else:
        evaluation = engine_eval(board, depth=8)
        cp = evaluation["cp"]
        bot_perspective = cp if board.turn == chess.BLACK else -cp
        bot_eval = bot_perspective
    accept = False
    if bot_eval <= -120 and random.random() < 0.55:
        accept = True
    elif abs(bot_eval) <= 60 and random.random() < 0.2:
        accept = True
    if accept:
        row = finish_game(gid, "draw", "agreement")
        return jsonify({"ok": True, "accepted": True, "state": game_state(row)})
    return jsonify({"ok": True, "accepted": False, "state": game_state(row)})


@app.route("/api/game/rematch", methods=["POST"])
def api_game_rematch():
    data = request.get_json(silent=True) or {}
    try:
        gid = int(data.get("game_id"))
    except (TypeError, ValueError):
        return json_error("Нет game_id")
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    if row["mode"] == "online":
        bot = make_online_bot(row["bot_elo"] or 1000, row["bot_name"] or None)
    else:
        bot = FAST_BOT if row["bot_elo"] == 1 else next(
            (item for item in BOTS if item["elo"] == row["bot_elo"]), None
        )
    if bot is None:
        return json_error("Бот не найден")
    new_color = "black" if row["user_color"] == "white" else "white"
    new_id = create_game(row["user_id"], row["mode"], bot, new_color, row["time_control"] or "10+0")
    return jsonify({"ok": True, "game_id": new_id})


@app.route("/api/analysis/<int:gid>")
def api_analysis(gid):
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    if row["status"] != "finished":
        return json_error("Анализ доступен только после партии")
    force = request.args.get("force") == "1"
    data = analyse_game(gid, force=force)
    if data is None:
        return json_error("Не удалось проанализировать партию", 500)
    user = current_user()
    coach = coach_for_user(user)
    user_color = data.get("user_color")
    for item in data.get("moves", []):
        item["is_user_move"] = item.get("color") == user_color
        item["text"] = coach_text(item, coach["style"])
    data["coach"] = coach
    data["coach_locked"] = bool(user and user["coach_id"])
    return jsonify({"ok": True, "analysis": data})


@app.route("/api/tournaments")
def api_tournaments():
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    return jsonify({"ok": True, "tournaments": tournament_info_for_user(user)})


@app.route("/api/tournament/<int:num>/start", methods=["POST"])
def api_tournament_start(num):
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    record, error = start_tournament(user["id"], num)
    if error:
        return json_error(error)
    return jsonify({
        "ok": True,
        "redirect": url_for("tournament_page", num=num),
        "status": record["status"],
    })


@app.route("/api/tournament/<int:num>")
def api_tournament(num):
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    item = TOURNAMENT_BY_NUM.get(num)
    if item is None:
        return json_error("Турнир не найден", 404)
    record = tournament_record(user["id"], num)
    unlocked, opens_at = tournament_is_open(user["id"], num)
    data = {
        "num": num,
        "name": item["name"],
        "rounds": item["rounds"],
        "lives": record["lives"] if record else item["lives"],
        "status": record["status"] if record else None,
        "unlocked": unlocked,
        "opens_at": opens_at,
        "left": days_left_text(opens_at) if opens_at else "открыт",
        "bracket": json.loads(record["bracket"]) if record else None,
        "current_round": record["current_round"] if record else 0,
    }
    return jsonify({"ok": True, "tournament": data})


@app.route("/api/tournament/<int:num>/play", methods=["POST"])
def api_tournament_play(num):
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    record = tournament_record(user["id"], num)
    if record is None or record["status"] != "active":
        return json_error("Турнир ещё не начат")
    gid, error = create_tournament_game(record)
    if error:
        return json_error(error)
    return jsonify({"ok": True, "game_id": gid})


@app.route("/import")
def import_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    return render_template("import.html")


def game_pgn_text(row):
    try:
        start_board = chess.Board(row["start_fen"]) if row["start_fen"] else chess.Board()
    except ValueError:
        start_board = chess.Board()
    user = fetch_user(row["user_id"]) if row["user_id"] else None
    player = user["username"] if user else "Игрок"
    bot_name = row["bot_name"] or "Соперник"
    user_color = row["user_color"] or "white"
    white = player if user_color == "white" else bot_name
    black = bot_name if user_color == "white" else player
    if row["result"] == "win":
        score = "1-0" if user_color == "white" else "0-1"
    elif row["result"] == "loss":
        score = "0-1" if user_color == "white" else "1-0"
    elif row["result"] == "draw":
        score = "1/2-1/2"
    else:
        score = "*"
    game = chess.pgn.Game()
    if start_board.fen() != chess.Board().fen():
        game.setup(start_board)
    game.headers["Event"] = "Chess.amy"
    game.headers["Site"] = "Chess.amy"
    game.headers["Date"] = (row["created_at"] or "")[:10].replace("-", ".") or "????.??.??"
    game.headers["White"] = white
    game.headers["Black"] = black
    game.headers["Result"] = score
    node = game
    for item in game_moves(row):
        try:
            node = node.add_variation(chess.Move.from_uci(item["uci"]))
        except ValueError:
            break
    return str(game)


def import_pgn_game(user, text):
    try:
        parsed = chess.pgn.read_game(io.StringIO(text))
    except (ValueError, RuntimeError):
        parsed = None
    if parsed is None:
        return None, "Не удалось разобрать PGN"
    board = parsed.board()
    moves = []
    for move in parsed.mainline_moves():
        try:
            san = board.san(move)
        except ValueError:
            break
        moves.append({
            "uci": move.uci(),
            "san": san,
            "color": "white" if board.turn == chess.WHITE else "black",
        })
        board.push(move)
    if not moves:
        return None, "В партии нет ходов"
    headers = parsed.headers
    username = (user["username"] or "").lower()
    user_color = "black" if username and username == (headers.get("Black") or "").lower() else "white"
    raw_result = (headers.get("Result") or "*").strip()
    result = None
    if raw_result in ("1-0", "0-1"):
        winner = "white" if raw_result == "1-0" else "black"
        result = "win" if winner == user_color else "loss"
    elif raw_result == "1/2-1/2":
        result = "draw"
    start_fen = None
    if headers.get("SetUp") == "1" and headers.get("FEN"):
        try:
            start_fen = chess.Board(headers["FEN"]).fen()
        except ValueError:
            start_fen = None
    bot_name = headers.get("Black") if user_color == "white" else headers.get("White")
    bot_name = (bot_name or "Импорт").strip()[:32] or "Импорт"
    with closing(get_db()) as db:
        cursor = db.execute(
            """INSERT INTO games (user_id, mode, bot_name, bot_elo, user_color, time_control,
            start_fen, pgn, moves, result, reason, timed, status, created_at, finished_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,0,'finished',?,?)""",
            (
                user["id"], "import", bot_name, 0, user_color, "10+0", start_fen,
                str(parsed), json.dumps(moves, ensure_ascii=False), result, "import",
                iso(now_utc()), iso(now_utc()),
            ),
        )
        gid = cursor.lastrowid
        db.commit()
    return gid, None


@app.route("/api/import/pgn", methods=["POST"])
def api_import_pgn():
    user = current_user()
    if user is None:
        return json_error("Импорт доступен с аккаунтом", 401)
    data = request.get_json(silent=True) or {}
    text = data.get("pgn") or ""
    if not text.strip():
        return json_error("Вставь PGN или загрузи файл")
    if len(text) > 400000:
        return json_error("Файл слишком большой")
    gid, error = import_pgn_game(user, text)
    if error:
        return json_error(error)
    return jsonify({
        "ok": True,
        "game_id": gid,
        "redirect": url_for("analysis_page", gid=gid),
    })


@app.route("/api/game/<int:gid>/export/pgn")
def api_export_pgn(gid):
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    text = game_pgn_text(row)
    user = fetch_user(row["user_id"]) if row["user_id"] else None
    name = f"{(user['username'] if user else 'chessamy')}-{gid}.pgn"
    return send_file(
        io.BytesIO(text.encode("utf-8")),
        mimetype="application/x-chess-pgn",
        as_attachment=True,
        download_name=name,
    )


@app.route("/api/game/<int:gid>/export/fen")
def api_export_fen(gid):
    row = load_game(gid)
    if row is None:
        return json_error("Партия не найдена", 404)
    if row["user_id"] and session.get("uid") != row["user_id"]:
        return json_error("Нет доступа", 403)
    board = board_for(row)
    start_board = chess.Board(row["start_fen"]) if row["start_fen"] else chess.Board()
    return jsonify({
        "ok": True,
        "fen": board.fen(),
        "start_fen": start_board.fen(),
        "move_number": board.fullmove_number,
        "turn": "white" if board.turn == chess.WHITE else "black",
    })


@app.route("/api/position/validate", methods=["POST"])
def api_validate_position():
    data = request.get_json(silent=True) or {}
    raw = (data.get("fen") or "").strip()
    if not raw:
        return json_error("Пустой FEN")
    try:
        board = chess.Board(raw)
    except ValueError:
        return json_error("Не удалось разобрать FEN")
    if board.king(chess.WHITE) is None or board.king(chess.BLACK) is None:
        return json_error("На доске должны быть оба короля")
    return jsonify({
        "ok": True,
        "fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "legal": [move.uci() for move in board.legal_moves],
        "over": board.is_game_over(),
        "check": board.is_check(),
    })


TRAINING_LABELS = ("brilliant", "amethyst", "ideal")


@app.route("/training")
def training_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    return render_template("training.html")


@app.route("/api/training/positions")
def api_training_positions():
    user = current_user()
    if user is None:
        return json_error("Тренировка доступна с аккаунтом", 401)
    positions = []
    with closing(get_db()) as db:
        rows = db.execute(
            """SELECT id, analysis, start_fen, user_color, moves, created_at
            FROM games WHERE user_id=? AND analysis IS NOT NULL AND analysis != ''
            ORDER BY id DESC LIMIT 120""",
            (user["id"],),
        ).fetchall()
    for row in rows:
        try:
            data = json.loads(row["analysis"])
        except (TypeError, ValueError):
            continue
        moves = data.get("moves") or []
        if not moves:
            continue
        user_color = row["user_color"] or "white"
        board = board_from_moves([], row["start_fen"])
        boards = [board.copy()]
        for item in game_moves(row):
            try:
                board.push(chess.Move.from_uci(item["uci"]))
            except ValueError:
                break
            boards.append(board.copy())
        for info in moves:
            if info.get("label") not in TRAINING_LABELS:
                continue
            if info.get("color") != user_color:
                continue
            ply = int(info.get("ply") or 0)
            if ply < 0 or ply >= len(boards):
                continue
            before = boards[ply]
            uci = info.get("uci") or ""
            if len(uci) < 4:
                continue
            positions.append({
                "game_id": row["id"],
                "ply": ply,
                "fen": before.fen(),
                "san": info.get("san") or "",
                "label": info.get("label"),
                "uci": uci,
                "from": uci[:2],
                "to": uci[2:4],
                "created_at": row["created_at"],
            })
    random.shuffle(positions)
    total = len(positions)
    return jsonify({
        "ok": True,
        "total": total,
        "positions": positions[:12],
        "labels": list(TRAINING_LABELS),
    })


@app.route("/api/profile")
def api_profile():
    user = current_user()
    if user is None:
        return json_error("Нужен аккаунт", 401)
    return jsonify({
        "ok": True,
        "user": user_json(user),
        "stats": profile_stats(user["id"]),
    })


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    user = current_user()
    if user is None:
        return json_error("Настройки доступны с аккаунтом", 401)
    if request.method == "GET":
        return jsonify({"ok": True, "settings": get_user_settings(user["id"])})
    data = request.get_json(silent=True) or {}
    values = {}
    if "bot_delay" in data:
        try:
            values["bot_delay"] = float(data["bot_delay"])
        except (TypeError, ValueError):
            return json_error("Задержка бота — число от 1 до 5 секунд")
    if "theme" in data:
        theme = str(data.get("theme") or "").strip().lower()
        if theme not in ("light", "dark"):
            return json_error("Тема: светлая или тёмная")
        values["theme"] = theme
    if "sound" in data:
        values["sound"] = bool(data.get("sound"))
    if "coordinates" in data:
        values["coordinates"] = bool(data.get("coordinates"))
    if "board_theme" in data:
        board_theme = str(data.get("board_theme") or "").strip().lower()
        if board_theme not in BOARD_THEMES and board_theme != "custom":
            return json_error("Неизвестная тема доски")
        values["board_theme"] = board_theme
    if "board_light" in data:
        light = str(data.get("board_light") or "").strip()
        if not HEX_COLOR_RE.match(light):
            return json_error("Цвет светлых клеток — в формате #rrggbb")
        values["board_light"] = light
    if "board_dark" in data:
        dark = str(data.get("board_dark") or "").strip()
        if not HEX_COLOR_RE.match(dark):
            return json_error("Цвет тёмных клеток — в формате #rrggbb")
        values["board_dark"] = dark
    if "piece_speed" in data:
        try:
            speed = int(float(data.get("piece_speed")))
        except (TypeError, ValueError):
            return json_error("Скорость фигур — число от 120 до 600 мс")
        if speed < 120 or speed > 600:
            return json_error("Скорость фигур — число от 120 до 600 мс")
        values["piece_speed"] = speed
    settings = save_user_settings(user["id"], values)
    return jsonify({"ok": True, "settings": settings})


@app.route("/backups")
def backups_page():
    user = current_user()
    if user is None:
        return redirect(url_for("index", need_account=1))
    try:
        db_size = DB_PATH.stat().st_size
    except OSError:
        db_size = 0
    return render_template(
        "backups.html",
        backups=list_backups(),
        db_size=db_size,
        db_path=str(DB_PATH),
    )


@app.route("/api/backups")
def api_backups():
    if current_user() is None:
        return json_error("Нужен аккаунт", 401)
    return jsonify({"ok": True, "backups": list_backups()})


@app.route("/api/backups/create", methods=["POST"])
def api_backups_create():
    if current_user() is None:
        return json_error("Нужен аккаунт", 401)
    name = create_backup_file()
    if not name:
        return json_error("База ещё не создана")
    return jsonify({"ok": True, "name": name, "backups": list_backups()})


@app.route("/api/backups/restore", methods=["POST"])
def api_backups_restore():
    if current_user() is None:
        return json_error("Нужен аккаунт", 401)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not restore_backup_file(name):
        return json_error("Копия не найдена или повреждена")
    if fetch_user(session.get("uid")) is None:
        session.clear()
        return jsonify({"ok": True, "restored": name, "redirect": url_for("index")})
    return jsonify({"ok": True, "restored": name, "backups": list_backups()})


@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/api/"):
        return json_error("Маршрут не найден", 404)
    return redirect(url_for("menu"))


@app.errorhandler(500)
def handle_500(error):
    if request.path.startswith("/api/"):
        return json_error("Внутренняя ошибка сервера", 500)
    return redirect(url_for("menu"))


CHEAT_PORT_DEFAULT = "5001"
CHEAT_DIR_NAMES = ("ChessAmyCH",)


def find_cheat_dir():
    parents = [BASE_DIR.parent, BASE_DIR, BASE_DIR.parent.parent]
    for parent in parents:
        for name in CHEAT_DIR_NAMES:
            candidate = parent / name
            if candidate != BASE_DIR and (candidate / "app.py").exists():
                return candidate
    return None


def start_cheat_server(port):
    if os.environ.get("CHESSAMY_NO_CHEAT") == "1":
        return None
    cheat_dir = find_cheat_dir()
    if cheat_dir is None:
        return None
    cheat_port = os.environ.get("CHEAT_PORT", CHEAT_PORT_DEFAULT)
    if str(cheat_port) == str(port):
        return None
    env = dict(os.environ)
    env["PORT"] = str(cheat_port)
    try:
        proc = subprocess.Popen(
            [sys.executable, "app.py"],
            cwd=str(cheat_dir),
            env=env,
        )
    except OSError:
        return None
    print(f"Чит-версия: http://127.0.0.1:{cheat_port}")
    atexit.register(proc.terminate)
    return proc


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print("Chess.amy")
    print(f"Stockfish: {STOCKFISH_PATH or 'не найден, включён учебный движок'}")
    print(f"Открой http://127.0.0.1:{port}")
    start_cheat_server(port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
