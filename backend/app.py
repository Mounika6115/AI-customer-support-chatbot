import os
from datetime import timedelta
from pathlib import Path
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_jwt_extended.exceptions import JWTExtendedException, NoAuthorizationError
from flask_limiter import Limiter
from jwt import ExpiredSignatureError, InvalidTokenError
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from dotenv import load_dotenv
from werkzeug.exceptions import HTTPException
from models import db
from routes.auth import auth_bp
from routes.api import api_bp
from routes.admin import admin_bp
from routes.eval import eval_bp

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


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
    # "*" = allow any evaluator origin (dashboard posts cross-origin).
    if "*" in origins:
        return "*"
    return origins


def is_serverless():
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
                or os.getenv("LAMBDA_TASK_ROOT"))

socketio = SocketIO(cors_allowed_origins=get_cors_origins(), async_mode="threading")
jwt = JWTManager()

@socketio.on("join")
def _on_join(data):
    from flask_socketio import join_room
    room = (data or {}).get("room") or (f"conversation_{(data or {}).get('conversation_id')}" if (data or {}).get("conversation_id") else None)
    if room:
        join_room(room)

@socketio.on("join_conversation")
def _on_join_conversation(data):
    from flask_socketio import join_room
    cid = (data or {}).get("conversation_id")
    if cid:
        join_room(f"conversation_{cid}")

def create_app():
    app=Flask(__name__)
    app.config["SECRET_KEY"]=os.getenv("SECRET_KEY","dev-only-change-me-to-a-longer-random-string")
    app.config["JWT_SECRET_KEY"]=os.getenv("JWT_SECRET_KEY","dev-jwt-change-me-to-a-longer-random-string")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"]=timedelta(days=7)
    app.config["SQLALCHEMY_DATABASE_URI"]=resolve_database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    # pool_pre_ping avoids stale pooled connections on hosted Postgres
    # (Neon/Supabase); harmless for local SQLite.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"]={"pool_pre_ping": True}
    origins = get_cors_origins()
    # browsers reject Access-Control-Allow-Origin:* with credentials, so only
    # send credentials for an explicit allowlist; eval routes use per-route "*".
    CORS(app, origins=origins, supports_credentials=(origins != "*"))
    db.init_app(app); jwt.init_app(app)
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
    Limiter(get_remote_address, app=app, default_limits=["120 per minute"])
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
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
    if is_serverless():
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
    else:
        socketio.run(
            app,
            host="0.0.0.0",
            port=5000,
            debug=os.getenv("FLASK_ENV") == "development",
            allow_unsafe_werkzeug=True,
        )
