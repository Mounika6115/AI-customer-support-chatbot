"""Regression tests for the comparison, follow-up context, and after-sales fixes."""
from app import create_app
from models import ReturnRequest, ServiceRequest, User, db
from services.ai import generate_reply
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


def _demo_id(app):
    with app.app_context():
        return User.query.filter_by(email=DEMO).first().id


def test_comparison_includes_pulse_pro_price_and_attributes():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("Compare Pulse Pro with Orbit Watch", cid, model="mock")
        reply = out["reply"].lower()
        assert "pulse pro" in reply and "orbit watch" in reply
        assert "149" in reply
        assert "warranty" in reply and "specifications" in reply
        assert "availability" in reply
        names = {p["product_name"] for p in out["products"]}
        assert {"Pulse Pro", "Orbit Watch"} <= names


def test_comparison_across_categories_keeps_both_products():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("Compare the Pulse Pro with the Nova X1 Smartphone",
                             cid, model="mock")
        names = {p["product_name"] for p in out["products"]}
        assert {"Pulse Pro", "Nova X1 Smartphone"} <= names
        assert "149" in out["reply"] and "699" in out["reply"]


def test_aero_warranty_followup_uses_most_recent_product():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        history = [
            {"role": "customer", "content": "Show me the Pulse Pro"},
            {"role": "ai", "content": "Pulse Pro (149.0)."},
            {"role": "customer", "content": "Tell me about the AeroBook"},
            {"role": "ai", "content": "AeroBook 14 (1099.0)."},
        ]
        out = generate_reply("What is its warranty?", cid,
                             conversation_history=history, model="mock")
        assert "aerobook 14" in out["reply"].lower()
        assert "2 years" in out["reply"]
        assert "pulse pro" not in out["reply"].lower()


def test_aero_warranty_followup_via_api_conversation():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    first = c.post("/api/chat", json={"message": "Tell me about AeroBook", "model": "mock"},
                   headers=h).get_json()
    second = c.post(f"/api/conversations/{first['conversation_id']}/message",
                    json={"message": "What is its warranty?", "model": "mock"},
                    headers=h).get_json()
    assert "aerobook" in second["reply"].lower()
    assert "2 years" in second["reply"]


def test_context_is_isolated_between_users():
    app = _fresh_app()
    with app.app_context():
        a = User.query.filter_by(email=DEMO).first()
        b = User(name="Other", email="other@example.com", role="customer")
        b.set_password(PWD)
        db.session.add(b)
        db.session.commit()
        first = generate_reply("Tell me about AeroBook", a.id, model="mock")
        history = [{"role": "customer", "content": "Tell me about AeroBook"},
                   {"role": "ai", "content": first["reply"]}]
        other = generate_reply("What is its warranty?", b.id,
                               conversation_history=[], model="mock")
        assert "aerobook" not in other["reply"].lower()
        followup = generate_reply("What is its warranty?", a.id,
                                  conversation_history=history, model="mock")
        assert "2 years" in followup["reply"]


def test_named_warranty_question_does_not_open_ticket():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        before = ServiceRequest.query.count()
        out = generate_reply("What is the warranty of the AeroBook?", cid, model="mock")
        assert "2 years" in out["reply"]
        assert ServiceRequest.query.count() == before
        assert (out.get("action") or {}).get("type") == "warranty_info"


def test_warranty_claim_question_uses_policy_without_ticket():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        before = ServiceRequest.query.count()
        out = generate_reply("How can I claim warranty?", cid, model="mock")
        assert "warranty" in out["reply"].lower()
        assert ServiceRequest.query.count() == before


def test_return_question_uses_policy_without_creating_return():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        before = ReturnRequest.query.count()
        out = generate_reply("How do I return my order?", cid, model="mock")
        assert "30 days" in out["reply"].lower()
        assert ReturnRequest.query.count() == before


def test_repair_request_links_matching_product_not_unrelated_order():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("My AC is not cooling, please repair", cid, model="mock")
        assert out["action"]["type"] == "service_request"
        assert out["action"]["product_id"]
        assert out["action"].get("order_id") is None


def test_multi_turn_followups_keep_aerobook_context():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        history, replies = [], {}
        for msg in ["Tell me about AeroBook 14", "What is its warranty?",
                    "How much is it?", "Is it available?",
                    "What are its specifications?", "What about returns?"]:
            out = generate_reply(msg, cid, conversation_history=list(history),
                                 model="mock")
            names = {p["product_name"] for p in out.get("products") or []}
            assert "AeroBook 14" in names, msg
            replies[msg] = out["reply"]
            history += [{"role": "customer", "content": msg},
                        {"role": "ai", "content": out["reply"]}]
        assert "2 years" in replies["What is its warranty?"]
        assert "1099" in replies["How much is it?"]
        assert "stock 12" in replies["Is it available?"].lower()
        assert "14-inch laptop" in replies["What are its specifications?"]
        assert "30-day return" in replies["What about returns?"].lower()
        # The return-policy follow-up must use AeroBook, not the unrelated
        # Pulse Pro order that happens to be the latest order on the account.
        assert "rd100235" not in replies["What about returns?"].lower()
        assert "pulse pro" not in replies["What is its warranty?"].lower()


def test_separate_conversations_do_not_mix_product_context():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    a = c.post("/api/chat", json={"message": "Tell me about AeroBook", "model": "mock"},
               headers=h).get_json()
    b = c.post("/api/chat", json={"message": "Show me the Pulse Pro", "model": "mock"},
               headers=h).get_json()
    assert a["conversation_id"] != b["conversation_id"]
    a2 = c.post(f"/api/conversations/{a['conversation_id']}/message",
                json={"message": "What is its warranty?", "model": "mock"},
                headers=h).get_json()
    b2 = c.post(f"/api/conversations/{b['conversation_id']}/message",
                json={"message": "What is its warranty?", "model": "mock"},
                headers=h).get_json()
    assert "aerobook" in a2["reply"].lower() and "2 years" in a2["reply"]
    assert "pulse pro" in b2["reply"].lower() and "1 year" in b2["reply"]
    assert "aerobook" not in b2["reply"].lower()


def test_warranty_policy_question_uses_warranty_policy():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("What is your warranty policy?", cid, model="mock")
        assert out["intent"] == "WARRANTY"
        assert (out.get("action") or {}).get("type") == "warranty_info"
        assert "warranty length depends" in out["reply"].lower()


def test_refund_policy_question_uses_refund_policy():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("What is your refund policy?", cid, model="mock")
        reply = out["reply"].lower()
        assert "24 hours" in reply or "5-7 business days" in reply
        assert "return policy" not in reply


def test_support_request_creates_service_request():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("I want to raise a service request", cid, model="mock")
        assert out["action"]["type"] == "service_request"
        assert out["action"]["request_number"].startswith("SRV")
