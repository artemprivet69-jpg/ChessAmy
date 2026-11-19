import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    pytest.importorskip("playwright.sync_api")
    port = _free_port()
    env = dict(os.environ)
    env["PORT"] = str(port)
    env["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="chessamy-e2e-")
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/", timeout=0.5)
            ready = True
            break
        except Exception:
            time.sleep(0.25)
    if not ready:
        proc.terminate()
        raise RuntimeError("Flask server did not start")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def browser(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()
