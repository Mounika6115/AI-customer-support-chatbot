"""Tests for production security fixes."""
import os
from app import create_app, is_production, validate_production_secrets
from models import db


def test_production_refuses_missing_secrets(monkeypatch):
    # Set production environment
    for k in ("ENV", "FLASK_ENV", "VERCEL_ENV", "VERCEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    try:
        validate_production_secrets()
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "SECRET_KEY" in str(e) or "JWT_SECRET_KEY" in str(e)


def test_production_refuses_weak_secrets(monkeypatch):
    for k in ("ENV", "FLASK_ENV", "VERCEL_ENV", "VERCEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("JWT_SECRET_KEY", "also-short")
    try:
        validate_production_secrets()
        assert False, "Should have raised"
    except RuntimeError:
        pass


def test_production_refuses_demo_secrets(monkeypatch):
    for k in ("ENV", "FLASK_ENV", "VERCEL_ENV", "VERCEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "supportflow-demo-secret-2026")
    monkeypatch.setenv("JWT_SECRET_KEY", "supportflow-demo-jwt-secret-2026")
    try:
        validate_production_secrets()
        assert False, "Should have raised"
    except RuntimeError:
        pass


def test_demo_accounts_not_seeded_in_production(monkeypatch):
    for k in ("ENV", "FLASK_ENV", "VERCEL_ENV", "VERCEL", "SKIP_SEED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    monkeypatch.setenv("JWT_SECRET_KEY", "b" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    app = create_app()
    with app.app_context():
        from models import User
        assert User.query.filter_by(email="customer@example.com").first() is None
        assert User.query.filter_by(email="admin@example.com").first() is None
        assert User.query.filter_by(email="agent@example.com").first() is None


def test_jwt_expiration_shorter():
    app = create_app()
    # Check expiration is set (1 hour now)
    assert app.config.get("JWT_ACCESS_TOKEN_EXPIRES").total_seconds() == 3600


def test_jwt_revocation_mechanism_exists():
    app = create_app()
    from models import TokenBlocklist
    assert TokenBlocklist.__tablename__ == "token_blocklist"
