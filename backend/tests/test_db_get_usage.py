"""Regression tests for db.session.get usage."""
from app import app
from services import tools
import inspect


def test_tools_use_db_session_get():
    src = inspect.getsource(tools)
    # should prefer db.session.get over Query.get in our modified code paths
    assert 'db.session.get' in src
