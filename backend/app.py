import os
from datetime import timedelta
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, decode_token
from flask_jwt_extended.exceptions import JWTExtendedException, NoAuthorizationError
from flask_limiter import Limiter
from jwt import ExpiredSignatureError, InvalidTokenError
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, join_room, disconnect
from dotenv import load_dotenv
from werkzeug.exceptions import HTTPException
from models import db, Conversation, TokenBlocklist, User
from routes.auth import auth_bp
from routes.api import api_bp
from routes.agent import agent_bp
from routes.admin import admin_bp
from routes.eval import eval_bp

BASE_DIR = Path(__file__).resolve().parent.parent
# AIRM-12: honor backend/.env first (backend-specific wins over root .env;
# real OS/Vercel env still wins over both). Missing files are a no-op.
load_dotenv(BASE_DIR / "backend" / ".env")
load_dotenv(BASE_DIR / ".env")


KNOWN_DEMO_SECRETS = {
    "supportflow-demo-secret-2026",
    "supportflow-demo-jwt-secret-2026",
    "dev-only-change-me-to-a-longer-random-string",
    "dev-jwt-change-me-to-a-longer-random-string",
    "change-me",
    "secret",
    "jwt-secret",
    "your_secret_key_here",
}


def validate_production_secrets():
    """Validate secrets in production/serverless environments.

    Refuses to start if SECRET_KEY or JWT_SECRET_KEY is missing, weak,
    or matches a known development/demo default.
    """
    if not is_production():
        return

    secret_key = os.getenv("SECRET_KEY")
    jwt_secret_key = os.getenv("JWT_SECRET_KEY")

    errors = []

    if not secret_key or not secret_key.strip():
        errors.append("SECRET_KEY")
    elif secret_key.strip() in KNOWN_DEMO_SECRETS or len(secret_key.strip()) < 32:
        errors.append("SECRET_KEY")

    if not jwt_secret_key or not jwt_secret_key.strip():
        errors.append("JWT_SECRET_KEY")
    elif jwt_secret_key.strip() in KNOWN_DEMO_SECRETS or len(jwt_secret_key.strip()) < 32:
        errors.append("JWT_SECRET_KEY")

    if errors:
        # Never log or print secret values
        raise RuntimeError(
            f"Missing or insecure secrets in production: {', '.join(sorted(set(errors)))}. "
            "Set strong, randomly generated SECRET_KEY and JWT_SECRET_KEY environment variables."
        )


def resolve_database_url():
    raw_url = os.getenv("DATABASE_URL", "sqlite:///support.db")
    # Vercel / AWS Lambda serverless functions have a read-only filesystem
    # except /tmp. A SQLite file bundled in the deployment (e.g.
    # backend/support.db) can be READ but any write (chat, tickets,
    # returns, ...) fails with "attempt to write a readonly database" and
    # every POST returns 500 "An unexpected error occurred." while GETs
    # keep working. Redirect SQLite to /tmp there (ephemeral but writable;
    # re-seeded on each cold start). For persistent production data use a
    # hosted DB (e.g. Neon/Supabase Postgres) via DATABASE_URL.
    if raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////"):
        if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("LAMBDA_TASK_ROOT"):
            return "sqlite:////tmp/support.db"
        relative_path = raw_url.replace("sqlite:///", "", 1)
        db_path = (Path(__file__).resolve().parent / relative_path).resolve()
        return f"sqlite:///{db_path}"
    return raw_url


def get_cors_origins():
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        return "*"
    return origins


def get_eval_cors_origins():
    """Evaluation CORS is an explicit allowlist and never inherits ``*``.

    ``EVAL_CORS_ORIGINS`` is independent from the app-wide allowlist so an
    operator can expose the normal UI without exposing evaluation routes (or
    vice versa). If it is unset, a non-wildcard ``CORS_ORIGINS`` is reused;
    a wildcard app allowlist is deliberately NOT copied to eval.
    """
    raw = os.getenv("EVAL_CORS_ORIGINS")
    if raw is None:
        raw = os.getenv("CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",")
            if origin.strip() and origin.strip() != "*"]


def is_serverless():
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
                or os.getenv("LAMBDA_TASK_ROOT"))


def is_production():
    """Production/serverless signals; eval mode must never be enabled here."""
    if is_serverless():
        return True
    if os.getenv("ENV", "").strip().lower() in ("production", "prod"):
        return True
    if os.getenv("FLASK_ENV", "").strip().lower() == "production":
        return True
    if os.getenv("VERCEL_ENV", "").strip().lower() == "production":
        return True
    return False


def is_eval_enabled():
    """The eval blueprint is opt-in, key-configured, and non-production."""
    return (os.getenv("EVAL_ENABLED", "").strip() == "1"
            and not is_production()
            and bool(os.getenv("EVAL_KEY", "").strip()))


def get_server_host():
    """Loopback by default; LAN exposure requires explicit ``HOST=0.0.0.0``."""
    return (os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1")


def is_werkzeug_dev_server_allowed():
    """Allow Werkzeug's development server only outside production.

    ``python app.py`` runs Flask-SocketIO in threading mode, which refuses to
    start when stdin is not a TTY unless this bypass is explicit. Local
    startup must work with debug off, so this is deliberately independent of
    ``is_debug_enabled()``. Production (including serverless) keeps the guard
    active; those deployments should use a real WSGI server.
    """
    return not is_production()


def is_debug_enabled():
    """Single gate for Werkzeug debug mode (debugger + reloader).

    Debug is ON only for explicit local development. It is OFF whenever any
    production signal is present — regardless of a stale ``FLASK_ENV`` value:
    serverless deployments, ``ENV=production``/``FLASK_ENV=production``, or
    ``FLASK_DEBUG=0``.
    """
    if is_serverless():
        return False
    if os.getenv("ENV", "").strip().lower() in ("production", "prod"):
        return False
    if os.getenv("FLASK_ENV", "").strip().lower() == "production":
        return False
    if os.getenv("FLASK_DEBUG", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    return (os.getenv("FLASK_ENV", "").strip().lower() == "development"
            or os.getenv("FLASK_DEBUG", "").strip() == "1")

socketio = SocketIO(cors_allowed_origins=get_cors_origins(), async_mode="threading")
jwt = JWTManager()


def _extract_token_from_socket(auth, args):
    token = None
    if isinstance(auth, dict):
        token = auth.get("token") or auth.get("Authorization") or auth.get("access_token")
    if not token and args:
        try:
            # sometimes passed as query
            pass
        except Exception:
            pass
    if not token:
        # try from headers via request context if available
        try:
            hdr = request.headers.get("Authorization") if request else None
            if hdr and hdr.lower().startswith("bearer "):
                token = hdr.split(" ", 1)[1]
        except Exception:
            pass
    if isinstance(token, str) and token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1]
    return token


def _authenticate_socket(auth=None, data=None, args=None):
    token = _extract_token_from_socket(auth, args)
    # also check data
    if not token and isinstance(data, dict):
        t = data.get("token") or data.get("access_token")
        if isinstance(t, str):
            if t.lower().startswith("bearer "):
                t = t.split(" ", 1)[1]
            token = t
    if not token:
        return None
    try:
        decoded = decode_token(token)
    except Exception:
        return None
    jti = decoded.get("jti")
    if jti:
        try:
            if TokenBlocklist.query.filter_by(jti=jti).first():
                return None
        except Exception:
            pass
    identity = decoded.get("sub") or decoded.get("identity")
    claims = decoded.get("claims") or {}
    role = (claims.get("role") or decoded.get("role") or "").strip().lower()
    try:
        user_id = int(identity) if identity is not None else None
    except Exception:
        user_id = None
    return {"user_id": user_id, "role": role, "claims": claims}


@socketio.on("join")
def _on_join(data, auth=None):
    auth_user = _authenticate_socket(auth=auth, data=data)
    if not auth_user or not auth_user.get("user_id"):
        disconnect()
        return
    room = (data or {}).get("room")
    cid = (data or {}).get("conversation_id")
    if cid and not room:
        room = f"conversation_{cid}"
    if not room:
        disconnect()
        return
    # verify access to conversation room if it's a conversation room
    try:
        if room.startswith("conversation_"):
            try:
                conv_id = int(room.split("conversation_")[-1])
            except Exception:
                conv_id = cid if isinstance(cid, int) or (isinstance(cid, str) and cid.isdigit()) else None
                if isinstance(conv_id, str):
                    conv_id = int(conv_id)
            if conv_id is not None:
                conv = db.session.get(Conversation, conv_id)
                if not conv:
                    disconnect()
                    return
                role = auth_user.get("role") or ""
                if conv.customer_id != auth_user.get("user_id") and role not in ("agent", "admin"):
                    disconnect()
                    return
    except Exception:
        disconnect()
        return
    join_room(room)


@socketio.on("join_conversation")
def _on_join_conversation(data, auth=None):
    auth_user = _authenticate_socket(auth=auth, data=data)
    if not auth_user or not auth_user.get("user_id"):
        disconnect()
        return
    cid = (data or {}).get("conversation_id")
    if not cid:
        disconnect()
        return
    try:
        conv_id = int(cid)
    except Exception:
        disconnect()
        return
    try:
        conv = db.session.get(Conversation, conv_id)
        if not conv:
            disconnect()
            return
        role = auth_user.get("role") or ""
        if conv.customer_id != auth_user.get("user_id") and role not in ("agent", "admin"):
            disconnect()
            return
    except Exception:
        disconnect()
        return
    join_room(f"conversation_{conv_id}")

def create_app():
    app=Flask(__name__)

    # Validate secrets in production before starting
    validate_production_secrets()

    if is_production():
        # In production, no fallbacks - must come from environment
        secret_key = os.getenv("SECRET_KEY")
        jwt_secret_key = os.getenv("JWT_SECRET_KEY")
        if not secret_key or not jwt_secret_key:
            raise RuntimeError("SECRET_KEY and JWT_SECRET_KEY must be set in production")
        app.config["SECRET_KEY"] = secret_key
        app.config["JWT_SECRET_KEY"] = jwt_secret_key
    else:
        app.config["SECRET_KEY"]=os.getenv("SECRET_KEY","dev-only-change-me-to-a-longer-random-string")
        app.config["JWT_SECRET_KEY"]=os.getenv("JWT_SECRET_KEY","dev-jwt-change-me-to-a-longer-random-string")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"]=timedelta(hours=1)  # Shorter expiration for better security
    app.config["JWT_REFRESH_TOKEN_EXPIRES"]=timedelta(days=30)
    app.config["SQLALCHEMY_DATABASE_URI"]=resolve_database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    # pool_pre_ping avoids stale pooled connections on hosted Postgres
    # (Neon/Supabase); harmless for local SQLite.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"]={"pool_pre_ping": True}
    origins = get_cors_origins()
    # browsers reject Access-Control-Allow-Origin:* with credentials, so only
    # send credentials for an explicit allowlist. Eval has a separate,
    # never-wildcarded resource rule (longest-prefix match wins in Flask-CORS).
    CORS(app, resources={
        r"/api/eval/*": {
            "origins": get_eval_cors_origins(),
            "supports_credentials": False,
        },
        r"/*": {
            "origins": origins,
            "supports_credentials": (origins != "*"),
        },
    })
    db.init_app(app); jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        from models import TokenBlocklist
        jti = jwt_payload["jti"]
        token = TokenBlocklist.query.filter_by(jti=jti).first()
        return token is not None

    # Vercel/AWS serverless functions do not support websockets: SocketIO is
    # local-dev only. REST + polling keep working; _emit() already no-ops.
    if not is_serverless():
        socketio.init_app(app)
    @jwt.invalid_token_loader
    def invalid_token_loader(error):
        return jsonify(error="Your session is invalid or expired. Please log in again."), 401
    @jwt.expired_token_loader
    def expired_token_loader(jwt_header, jwt_data):
        return jsonify(error="Your session is invalid or expired. Please log in again."), 401
    @jwt.unauthorized_loader
    def unauthorized_loader(error):
        return jsonify(error="Your session is invalid or expired. Please log in again."), 401
    @jwt.revoked_token_loader
    def revoked_token_loader(jwt_header, jwt_data):
        return jsonify(error="Your session is invalid or expired. Please log in again."), 401
    storage_uri = (
        os.getenv("RATELIMIT_STORAGE_URL")
        or os.getenv("REDIS_URL")
        or os.getenv("UPSTASH_REDIS_REST_URL")
        or os.getenv("REDIS_TLS_URL")
    )
    limiter_kwargs = {"key_func": get_remote_address, "app": app, "default_limits": ["120 per minute"]}
    if storage_uri:
        limiter_kwargs["storage_uri"] = storage_uri
    try:
        limiter = Limiter(**limiter_kwargs)
    except Exception:
        # Fall back to in-memory if shared store is unavailable
        try:
            limiter = Limiter(get_remote_address, app=app, default_limits=["120 per minute"])
        except Exception:
            limiter = Limiter(get_remote_address, app=app, default_limits=["120 per minute"])
    app.limiter = limiter
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(agent_bp, url_prefix="/api/agent")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    # Disabled by default: only register when explicitly enabled outside
    # production. The blueprint additionally requires X-Eval-Key on every
    # route (including health/results).
    if is_eval_enabled():
        app.register_blueprint(eval_bp, url_prefix="/api/eval")
    @app.get("/api/health")
    def health(): return {"status":"ok"}
    @app.errorhandler(NoAuthorizationError)
    @app.errorhandler(JWTExtendedException)
    @app.errorhandler(InvalidTokenError)
    @app.errorhandler(ExpiredSignatureError)
    def handle_jwt_error(e):
        return jsonify(error="Your session is invalid or expired. Please log in again."), 401
    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        return jsonify(error=e.description or e.name), e.code or 500
    @app.errorhandler(Exception)
    def err(e):
        app.logger.exception(e)
        return jsonify(error="An unexpected error occurred."),500
    with app.app_context():
        try:
            uri = app.config["SQLALCHEMY_DATABASE_URI"]
            if uri.startswith("sqlite:////tmp/"):
                os.makedirs("/tmp", exist_ok=True)
            db.create_all()
            # SKIP_SEED=1 for Ephemeral serverless cold starts where the caller
            # manages data externally; default still seeds the demo catalog so
            # a fresh /tmp SQLite DB is immediately usable for evaluation.
            if os.getenv("SKIP_SEED", "").strip() != "1":
                from services.seed import seed
                seed()
        except Exception:
            app.logger.exception("database init/seed failed")
    return app


app = create_app()


if __name__=="__main__":
    # Local `python app.py` only. Vercel imports `app` via api/index.py and
    # never executes this block. Defaults bind loopback with debug off;
    # LAN exposure needs an explicit HOST override. The Werkzeug
    # non-TTY bypass below is enabled for local development only, so the
    # production guard stays active everywhere else.
    if is_serverless():
        app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
    else:
        socketio.run(
            app,
            host=get_server_host(),
            port=int(os.getenv("PORT", "5000")),
            debug=is_debug_enabled(),
            allow_unsafe_werkzeug=is_werkzeug_dev_server_allowed(),
        )
