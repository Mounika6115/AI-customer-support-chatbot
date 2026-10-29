"""Regression tests for registration validation."""
from app import create_app
from models import db


def _fresh_app():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
    return app


def test_register_rejects_invalid_email():
    app = _fresh_app()
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": "Test", "email": "bademail", "password": "Password123"})
    assert r.status_code == 400
    assert "email" in str(r.get_json()).lower()


def test_register_rejects_weak_password_short():
    app = _fresh_app()
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": "Test", "email": "test@example.com", "password": "Pass1"})
    assert r.status_code == 400


def test_register_rejects_weak_password_no_upper():
    app = _fresh_app()
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": "Test", "email": "test@example.com", "password": "password123"})
    assert r.status_code == 400


def test_register_rejects_weak_password_no_number():
    app = _fresh_app()
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": "Test", "email": "test@example.com", "password": "Password"})
    assert r.status_code == 400


def test_register_accepts_valid_registration():
    app = _fresh_app()
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": "Test User", "email": "valid@example.com", "password": "Password123"})
    assert r.status_code == 201
