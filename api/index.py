"""Vercel serverless entrypoint: exposes the Flask app as `app`.

Vercel Python runtime looks for an `app` (or `handler`) object in
`api/index.py`. Websockets (Flask-SocketIO) are NOT supported on Vercel:
`backend/app.py` automatically skips `socketio.init_app()` when VERCEL=1,
so REST endpoints (including /api/eval/*) work while realtime falls back
to the frontend's 3s polling. For persistent websockets + database, deploy
the backend on Render/Railway/Fly instead (see README / .env.example).
"""
import os
import sys

CURRENT = os.path.dirname(__file__)
BACKEND = os.path.join(os.path.dirname(CURRENT), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("VERCEL", "1")

from app import app  # noqa: E402  (Vercel looks for `app`)
