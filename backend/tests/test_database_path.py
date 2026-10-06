from pathlib import Path

from app import create_app
from models import User, db


def test_app_uses_backend_sqlite_path_and_seeded_demo_account():
    app = create_app()

    with app.app_context():
        db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        backend_db = (Path(__file__).resolve().parents[1] / "support.db").as_posix()

        assert db_uri.endswith(f"/{backend_db.split('/')[-1]}")
        assert db_uri.startswith("sqlite:////")
        assert User.query.filter_by(email="customer@example.com").first() is not None


def test_invalid_jwt_returns_clean_session_error():
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/chat",
        json={"message": "hello"},
        headers={"Authorization": "Bearer invalid.token.value"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Your session is invalid or expired. Please log in again."
