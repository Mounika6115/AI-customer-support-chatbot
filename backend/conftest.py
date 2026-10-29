"""AIRM-32: pytest isolation guard — tests must never touch backend/support.db.

Why this exists:
- ``backend/app.py`` resolves ``DATABASE_URL=sqlite:///support.db`` to the
  real file ``backend/support.db`` and ``create_app()`` runs
  ``db.create_all()`` + ``seed()`` at import/call time.
- Several tests call ``db.drop_all()/db.create_all()``, which would wipe the
  live dev database when ``DATABASE_URL`` is unset.
- There is no pytest config, so running from the repo root fails with
  ``ModuleNotFoundError: app`` because ``backend/`` is not on ``sys.path``.

What this does (test-only, no app behavior change):
1. Puts ``backend/`` on ``sys.path`` so ``from app import ...`` works from
   any working directory (repo root or ``backend/``).
2. Forces ``DATABASE_URL`` to a fresh file under ``/tmp/`` unless the caller
   already pointed it at an isolated location (``/tmp/``, ``:memory:`` or a
   path containing ``pytest``). This runs before any test module imports
   ``app`` (conftest loads first), including ``app.py``'s module-level
   ``app = create_app()``.
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _is_isolated(url: str) -> bool:
    # NOTE: empty/unset means "use the default backend/support.db" — that is
    # the live DB, so it is NEVER treated as isolated.
    u = (url or "").strip()
    return bool(u) and (
        u.startswith("sqlite:////tmp/")
        or u.startswith("sqlite:///:memory:")
        or "pytest" in u
        or "/tmp/" in u
    )


if not _is_isolated(os.getenv("DATABASE_URL", "")):
    tmpdir = tempfile.mkdtemp(prefix="supportflow-tests-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmpdir}/test-support.db"

# Enable eval endpoints for existing tests that rely on them (tests run in
# non-production, local environment). The shared key is test-only.
os.environ.setdefault("EVAL_ENABLED", "1")
os.environ.setdefault("EVAL_KEY", "test-eval-key")
os.environ.setdefault("EVAL_CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("EVAL_ALLOW_WRITES", "1")
