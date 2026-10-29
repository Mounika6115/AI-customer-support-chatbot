"""Regression tests for rate limiting configuration."""
from app import create_app


def test_app_has_limiter():
    app = create_app()
    assert hasattr(app, 'limiter')
