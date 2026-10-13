"""AIRM-41 Phase 1: human handoff regression tests (deterministic, mock AI)."""
from app import create_app
from models import db, Message
from services.ai import generate_reply, is_escalation_request
from services.seed import seed

DEMO = "customer@example.com"
AGENT = "agent@example.com"
ADMIN = "admin@example.com"
PWD = "Demo123!"


def _fresh_app():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed()
    return app


def _token(c, email):
    return c.post("/api/auth/login",
                  json={"email": email, "password": PWD}).get_json()["token"]


def _start_handoff(c, headers):
    return c.post("/api/chat", json={"message": "I want to talk to a human agent"},
                  headers=headers).get_json()


def test_escalation_only_on_explicit_request():
    assert is_escalation_request("I want to talk to a human agent")
    assert is_escalation_request("Please connect me to an agent")
    for msg in ("I want to book a service", "Create a service ticket",
                "My AC is not cooling, please repair", "Where is my previous order?",
                "Hi", "I want to return my product"):
        assert not is_escalation_request(msg), msg


def test_handoff_flow_customer_to_waiting_and_ai_silent():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    j = _start_handoff(c, h)
    assert j["escalate"] is True and j["status"] == "WAITING_FOR_AGENT"
    cid = j["conversation_id"]
    r2 = c.post(f"/api/conversations/{cid}/message",
                json={"message": "Are you still there?"}, headers=h)
    assert r2.get_json()["status"] == "WAITING_FOR_AGENT"
    with app.app_context():
        ai_msgs = Message.query.filter_by(conversation_id=cid, sender_type="AI").all()
        assert len(ai_msgs) == 1  # only the handoff acknowledgement


def test_agent_queue_requires_agent_role():
    app = _fresh_app()
    c = app.test_client()
    ch = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    ah = {"Authorization": f"Bearer {_token(c, AGENT)}"}
    adminh = {"Authorization": f"Bearer {_token(c, ADMIN)}"}
    cid = _start_handoff(c, ch)["conversation_id"]
    assert c.get("/api/agent/queue", headers=ch).status_code == 403
    assert c.get("/api/agent/queue", headers=adminh).status_code == 403
    q = c.get("/api/agent/queue", headers=ah).get_json()
    assert any(x["id"] == cid and x["status"] == "WAITING_FOR_AGENT" for x in q)


def test_claim_reply_and_customer_receives():
    from models import User
    app = _fresh_app()
    c = app.test_client()
    ch = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    ah = {"Authorization": f"Bearer {_token(c, AGENT)}"}
    cid = _start_handoff(c, ch)["conversation_id"]
    # customer cannot claim or reply as agent
    assert c.post(f"/api/agent/conversations/{cid}/claim", headers=ch).status_code == 403
    assert c.post(f"/api/agent/conversations/{cid}/reply",
                  json={"message": "x"}, headers=ch).status_code == 403
    # reply before claim is rejected
    assert c.post(f"/api/agent/conversations/{cid}/reply",
                  json={"message": "x"}, headers=ah).status_code == 403
    # claim works, second agent gets 409
    assert c.post(f"/api/agent/conversations/{cid}/claim", headers=ah).get_json()["status"] == "AGENT_ACTIVE"
    with app.app_context():
        a2 = User(name="Agent Two", email="agent2@example.com", role="agent")
        a2.set_password(PWD)
        db.session.add(a2)
        db.session.commit()
    a2h = {"Authorization": f"Bearer {_token(c, 'agent2@example.com')}"}
    assert c.post(f"/api/agent/conversations/{cid}/claim", headers=a2h).status_code == 409
    # agent replies, customer receives it
    c.post(f"/api/agent/conversations/{cid}/reply",
           json={"message": "Hi, I can help with your order."}, headers=ah)
    d = c.get(f"/api/conversations/{cid}", headers=ch).get_json()
    agents = [m for m in d["messages"] if m["sender"] == "agent"]
    assert agents and "help with your order" in agents[0]["content"]


def test_ai_silent_after_claim():
    app = _fresh_app()
    c = app.test_client()
    ch = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    ah = {"Authorization": f"Bearer {_token(c, AGENT)}"}
    cid = _start_handoff(c, ch)["conversation_id"]
    c.post(f"/api/agent/conversations/{cid}/claim", headers=ah)
    with app.app_context():
        before = Message.query.filter_by(conversation_id=cid, sender_type="AI").count()
    r = c.post(f"/api/conversations/{cid}/message",
               json={"message": "Where is my order?"}, headers=ch).get_json()
    assert r["status"] == "AGENT_ACTIVE"
    with app.app_context():
        after = Message.query.filter_by(conversation_id=cid, sender_type="AI").count()
        assert after == before


def test_no_false_handoff_preserves_flows():
    from models import User
    app = _fresh_app()
    with app.app_context():
        cid = User.query.filter_by(email=DEMO).first().id
        out = generate_reply("My AC is not cooling, please arrange a repair",
                             cid, model="mock")
        assert out["escalate"] is False and out["action"].get("ok") is True
        out = generate_reply("Where is my previous order?", cid, model="mock")
        assert out["escalate"] is False and out["order"] is not None
        out = generate_reply("I want to talk to a human agent", cid, model="mock")
        assert out["escalate"] is True and out["model_used"] == "handoff"


def test_claim_closed_conversation_rejected():
    from models import Conversation
    app = _fresh_app()
    c = app.test_client()
    ch = {"Authorization": f"Bearer {_token(c, DEMO)}"}
    ah = {"Authorization": f"Bearer {_token(c, AGENT)}"}
    cid = _start_handoff(c, ch)["conversation_id"]
    c.post(f"/api/agent/conversations/{cid}/claim", headers=ah)
    with app.app_context():
        conv = Conversation.query.get(cid)
        conv.status = "CLOSED"
        db.session.commit()
    r = c.post(f"/api/agent/conversations/{cid}/claim", headers=ah)
    assert r.status_code == 400
    with app.app_context():
        assert Conversation.query.get(cid).status == "CLOSED"
