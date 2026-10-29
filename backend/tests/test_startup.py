"""Regression test: local startup must work with debug explicitly disabled.

Flask-SocketIO refuses to use Werkzeug's server from a non-TTY unless
``allow_unsafe_werkzeug`` is set. The test launches ``python app.py`` exactly
like a developer/CI would (pipes are not a TTY), with debug off, and checks
that ``/api/health`` is reachable.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _startup_env(port, db_path):
    env = os.environ.copy()
    for var in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "LAMBDA_TASK_ROOT",
                "ENV", "FLASK_ENV", "FLASK_DEBUG", "HOST", "PORT"):
        env.pop(var, None)
    env.update({
        "FLASK_DEBUG": "0",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "DATABASE_URL": f"sqlite:///{db_path}",
        # Schema creation is enough for /api/health; skip demo seeding.
        "SKIP_SEED": "1",
    })
    return env


def test_app_starts_with_debug_disabled_and_health_ok(tmp_path):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=BACKEND_DIR,
        env=_startup_env(port, tmp_path / "startup.db"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 30
        last_error = None
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read()
                pytest.fail(
                    f"app.py exited with {proc.returncode} before serving "
                    f"/api/health:\n{output}"
                )
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=1
                ) as response:
                    assert response.status == 200
                    assert json.loads(response.read()) == {"status": "ok"}
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
                last_error = exc
                time.sleep(0.2)

        output = ""
        if proc.poll() is not None:
            output = proc.stdout.read()
        pytest.fail(
            f"app.py did not serve /api/health within 30s: {last_error}\n{output}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
