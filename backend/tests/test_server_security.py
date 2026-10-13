"""AIRM-18: debug-server exposure regression tests (no DB writes)."""
from pathlib import Path

from app import get_server_host, is_debug_enabled


def _clean_env(monkeypatch):
    for var in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "LAMBDA_TASK_ROOT",
                "ENV", "FLASK_ENV", "FLASK_DEBUG", "HOST", "PORT"):
        monkeypatch.delenv(var, raising=False)


def test_default_host_is_loopback(monkeypatch):
    _clean_env(monkeypatch)
    assert get_server_host() == "127.0.0.1"


def test_host_override_is_respected(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("HOST", "0.0.0.0")
    assert get_server_host() == "0.0.0.0"


def test_debug_off_by_default(monkeypatch):
    _clean_env(monkeypatch)
    assert is_debug_enabled() is False


def test_debug_on_for_local_development(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("FLASK_ENV", "development")
    assert is_debug_enabled() is True


def test_debug_off_when_serverless_even_if_development(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("VERCEL", "1")
    assert is_debug_enabled() is False


def test_debug_off_in_production_regardless_of_flask_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("ENV", "production")
    assert is_debug_enabled() is False
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")
    assert is_debug_enabled() is False


def test_debug_kill_switch(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    assert is_debug_enabled() is False


def test_main_block_has_no_wildcard_bind_or_unsafe_flag():
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    main = src.split("__main__")[-1]
    assert 'host="0.0.0.0"' not in main and "host='0.0.0.0'" not in main
    # The Werkzeug non-TTY bypass may only ever be gated on local debug mode,
    # never unconditionally enabled.
    assert "allow_unsafe_werkzeug=True" not in main
    assert "allow_unsafe_werkzeug = True" not in main
