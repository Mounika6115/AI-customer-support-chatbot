from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt
from models import db, User, TokenBlocklist
from datetime import datetime, timezone
import re
auth_bp = Blueprint("auth", __name__)


def is_production_env():
    import os
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("LAMBDA_TASK_ROOT"):
        return True
    if os.getenv("ENV", "").strip().lower() in ("production", "prod"):
        return True
    if os.getenv("FLASK_ENV", "").strip().lower() == "production":
        return True
    if os.getenv("VERCEL_ENV", "").strip().lower() == "production":
        return True
    return False


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_password(pw: str):
    if not isinstance(pw, str):
        return False, "Password does not meet requirements"
    if len(pw) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", pw):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", pw):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"[0-9]", pw):
        return False, "Password must contain at least one number"
    return True, None


def _apply_rate_limit(limit_str):
    try:
        limiter = getattr(current_app, "limiter", None)
        if limiter is None:
            return lambda f: f
        from flask_limiter.util import get_remote_address
        return limiter.limit(limit_str, key_func=get_remote_address)
    except Exception:
        return lambda f: f


@auth_bp.post("/register")
@_apply_rate_limit("10 per minute")
def register():
    d = request.get_json() or {}
    if not all(d.get(k) for k in ("name", "email", "password")):
        return {"error": "Missing required fields"}, 400
    email = str(d.get("email") or "").strip().lower()
    name = str(d.get("name") or "").strip()
    password = d.get("password") or ""
    if not name:
        return {"error": "Missing required fields"}, 400
    if not EMAIL_RE.match(email):
        return {"error": "Invalid email format"}, 400
    ok_pw, pw_err = _validate_password(password)
    if not ok_pw:
        return {"error": pw_err}, 400
    if User.query.filter_by(email=email).first():
        return {"error": "Email already registered"}, 409
    # Prevent creating demo accounts in production
    if is_production_env() and email in ("customer@example.com", "admin@example.com", "agent@example.com"):
        return {"error": "Registration not allowed"}, 403
    u = User(name=name, email=email, role="customer")
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return {"message": "registered"}, 201


@auth_bp.post("/login")
@_apply_rate_limit("5 per minute")
def login():
    d = request.get_json() or {}
    email = str(d.get("email") or "").strip().lower()
    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(d.get("password", "")):
        return {"error": "Invalid credentials"}, 401
    return {"token": create_access_token(identity=str(u.id), additional_claims={"role": u.role, "name": u.name}), "user": {"id": u.id, "name": u.name, "role": u.role}}


@auth_bp.post("/logout")
@jwt_required()
def logout():
    try:
        jti = get_jwt()["jti"]
        token_type = get_jwt()["type"]
        exp_timestamp = get_jwt().get("exp")
        exp = (datetime.fromtimestamp(exp_timestamp, tz=timezone.utc).replace(tzinfo=None) if exp_timestamp else None)
        blocked_token = TokenBlocklist(jti=jti, token_type=token_type, revoked_at=datetime.now(timezone.utc).replace(tzinfo=None), expires_at=exp)
        db.session.add(blocked_token)
        db.session.commit()
        return {"message": "Successfully logged out"}, 200
    except Exception:
        db.session.rollback()
        return {"message": "Successfully logged out"}, 200


@auth_bp.post("/revoke")
@jwt_required()
def revoke():
    try:
        jti = get_jwt()["jti"]
        token_type = get_jwt()["type"]
        exp_timestamp = get_jwt().get("exp")
        exp = (datetime.fromtimestamp(exp_timestamp, tz=timezone.utc).replace(tzinfo=None) if exp_timestamp else None)
        if not TokenBlocklist.query.filter_by(jti=jti).first():
            blocked_token = TokenBlocklist(jti=jti, token_type=token_type, revoked_at=datetime.now(timezone.utc).replace(tzinfo=None), expires_at=exp)
            db.session.add(blocked_token)
            db.session.commit()
        return {"message": "Token revoked"}, 200
    except Exception:
        db.session.rollback()
        return {"message": "Token revoked"}, 200
