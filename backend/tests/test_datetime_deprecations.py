"""Regression tests for datetime usage."""
from routes import auth, api
from models import __init__ as models_init
from services import seed, tools
import inspect


def test_no_utcnow_calls():
    for mod in [auth, api, models_init, seed, tools]:
        try:
            src = inspect.getsource(mod)
        except Exception:
            continue
        assert 'utcnow()' not in src
