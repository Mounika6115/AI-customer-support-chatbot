"""AIRM-46: chat session and new-chat behavior (deterministic, mock AI)."""
from app import create_app
from models import db, Message, User
from services.seed import seed

DEMO = "customer@example.com"
PWD = "Demo123!"


def _fresh_app():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed()
    return app


def _token(c, email, password=PWD):
    return c.post("/api/auth/login",
                  json={"email": email, "password": password}).get_json()["token"]


def _second_user_token(c):
    with c.application.app_context():
        if not User.query.filter_by(email="second@example.com").first():
            u = User(name="Second", email="second@example.com", role="customer")
            u.set_password(PWD)
            db.session.add(u)
            db.session.commit()
    return _token(c, "second@example.com")


def test_new_chats_get_distinct_ids():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    a = c.post("/api/chat", json={"message": "Hi"}, headers=h).get_json()
    b = c.post("/api/chat", json={"message": "Hello"}, headers=h).get_json()
    assert a["conversation_id"] != b["conversation_id"]
    for cid in (a["conversation_id"], b["conversation_id"]):
        msgs = c.get(f"/api/conversations/{cid}", headers=h).get_json()["messages"]
        assert len(msgs) == 2  # exactly its own customer + AI messages


def test_history_isolated_between_conversations():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    a = c.post("/api/chat", json={"message": "Where is my previous order?"},
               headers=h).get_json()
    assert "RD100" in a["reply"]
    b = c.post("/api/chat", json={"message": "What is the warranty of Unicorn Phone X99?"},
               headers=h).get_json()
    assert b["conversation_id"] != a["conversation_id"]
    assert "RD100" not in b["reply"]
    msgs = c.get(f"/api/conversations/{b['conversation_id']}", headers=h).get_json()["messages"]
    assert len(msgs) == 2


def test_close_success_and_idempotent():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    cid = c.post("/api/chat", json={"message": "Hi"}, headers=h).get_json()["conversation_id"]
    r1 = c.post(f"/api/conversations/{cid}/close", headers=h).get_json()
    assert r1["status"] == "CLOSED"
    r2 = c.post(f"/api/conversations/{cid}/close", headers=h)
    assert r2.status_code == 200 and r2.get_json()["status"] == "CLOSED"


def test_message_to_closed_rejected_and_history_preserved():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    cid = c.post("/api/chat", json={"message": "Hi"}, headers=h).get_json()["conversation_id"]
    before = c.get(f"/api/conversations/{cid}", headers=h).get_json()["messages"]
    c.post(f"/api/conversations/{cid}/close", headers=h)
    r = c.post(f"/api/conversations/{cid}/message", json={"message": "Are you there?"}, headers=h)
    assert r.status_code == 400
    assert "closed" in r.get_json()["error"].lower()
    after = c.get(f"/api/conversations/{cid}", headers=h).get_json()
    assert after["status"] == "CLOSED"
    assert len(after["messages"]) == len(before)


def test_close_other_customers_conversation_404():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    h2 = {"Authorization": f"Bearer {_second_user_token(c)}"}
    cid = c.post("/api/chat", json={"message": "Hi"}, headers=h).get_json()["conversation_id"]
    assert c.post(f"/api/conversations/{cid}/close", headers=h2).status_code == 404
    assert c.post(f"/api/conversations/{cid}/message",
                  json={"message": "Hi"}, headers=h2).status_code == 404
    assert c.get(f"/api/conversations/{cid}", headers=h2).status_code == 404


def test_waiting_notice_persisted_and_deduped():
    from routes.api import WAITING_NOTICE
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    cid = c.post("/api/chat", json={"message": "I want to talk to a human agent"},
                 headers=h).get_json()["conversation_id"]
    c.post(f"/api/conversations/{cid}/message",
           json={"message": "Where is my order?"}, headers=h)
    c.post(f"/api/conversations/{cid}/message",
           json={"message": "Hello? anyone there?"}, headers=h)
    # polling/refresh view: notice survived, shown exactly once
    msgs = c.get(f"/api/conversations/{cid}", headers=h).get_json()["messages"]
    notices = [m for m in msgs if m["sender"] == "system" and m["content"] == WAITING_NOTICE]
    assert len(notices) == 1
    assert len([m for m in msgs if m["sender"] == "customer"]) == 3
    assert not [m for m in msgs if m["sender"] == "ai" and "order" in m["content"].lower()]


def test_conversations_list_shows_waiting():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    cid = c.post("/api/chat", json={"message": "I want to talk to a human agent"},
                 headers=h).get_json()["conversation_id"]
    convos = c.get("/api/conversations", headers=h).get_json()
    assert any(x["id"] == cid and x["status"] == "WAITING_FOR_AGENT" for x in convos)
