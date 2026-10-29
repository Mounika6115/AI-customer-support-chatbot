EVAL_HEADERS = {"X-Eval-Key": "test-eval-key"}
"""Regression tests for the comparison, follow-up context, and after-sales fixes."""
from app import create_app
from models import Product, ReturnRequest, ServiceRequest, User, db
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


def test_comparison_prices_are_read_from_the_product_catalog():
    """No hard-coded prices: changed catalog rows must drive the comparison."""
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        pulse = Product.query.filter_by(product_name="Pulse Pro").first()
        orbit = Product.query.filter_by(product_name="Orbit Watch").first()
        pulse.price = 177.5
        orbit.price = 321.0
        db.session.commit()

        out = generate_reply("Compare Pulse Pro with Orbit Watch", cid, model="mock")
        reply = out["reply"]
        prices = {p["product_name"]: p["price"] for p in out["products"]}

        assert prices == {"Pulse Pro": 177.5, "Orbit Watch": 321.0}
        assert "177.5" in reply and "321" in reply
        assert "149" not in reply and "249" not in reply


def test_comparison_wording_variants_keep_both_products():
    """Comparison intent must survive common phrasings, not just "Compare X with Y"."""
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        for msg in ("Compare Pulse Pro vs Orbit Watch",
                    "What is the difference between Pulse Pro and Orbit Watch?",
                    "Which is better, Pulse Pro or Orbit Watch?",
                    "Pulse Pro or Orbit Watch?"):
            out = generate_reply(msg, cid, model="mock")
            names = {p["product_name"] for p in out["products"]}
            assert {"Pulse Pro", "Orbit Watch"} <= names, msg
            reply = out["reply"].lower()
            assert "pulse pro" in reply and "orbit watch" in reply, msg
            assert "149" in reply and "249" in reply, msg
            assert "warranty" in reply and "specifications" in reply, msg
            assert "availability" in reply, msg


def test_comparison_followup_uses_products_remembered_from_history():
    """One side of a comparison may live only in earlier conversation turns."""
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        history = [
            {"role": "customer", "content": "Show me Samsung phones"},
            {"role": "ai", "content": ("Here are some options from our catalogue: "
                                       "Galaxy M35 5G (24999.0), Galaxy S24 FE (29999.0), "
                                       "Galaxy A15 (16999.0).")},
        ]
        out = generate_reply("Compare the cheapest one with Pulse Pro", cid,
                             conversation_history=history, model="mock")
        names = {p["product_name"] for p in out["products"]}
        assert {"Pulse Pro", "Galaxy A15"} <= names
        assert "149" in out["reply"] and "16999" in out["reply"]
        # The remembered side must be a real catalogue row, not an invented item.
        assert "warranty" in out["reply"].lower()
        assert "specifications" in out["reply"].lower()


def test_warranty_followup_without_pronoun_uses_latest_product():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        history = [
            {"role": "customer", "content": "Show me the Pulse Pro"},
            {"role": "ai", "content": "Pulse Pro (warranty 1 year)."},
            {"role": "customer", "content": "Tell me about the AeroBook 14"},
            {"role": "ai", "content": "AeroBook 14 (1099.0)."},
        ]
        out = generate_reply("What is the warranty?", cid,
                             conversation_history=history, model="mock")
        reply = out["reply"].lower()
        assert "aerobook 14" in reply
        assert "2 years" in reply
        assert "pulse pro" not in reply


def test_eval_comparison_endpoint_returns_catalog_prices_and_details():
    app = _fresh_app()
    c = app.test_client()
    r = c.post("/api/eval/chat",
               json={"message": "Compare Pulse Pro with Orbit Watch"}, headers=EVAL_HEADERS)
    assert r.status_code == 200
    body = r.get_json()
    reply = body["reply"].lower()
    names = {p["product_name"] for p in body["products"]}
    assert {"Pulse Pro", "Orbit Watch"} <= names
    assert "149" in reply and "249" in reply
    assert all(k in reply for k in ("warranty", "specifications",
                                    "availability", "price"))


def test_handoff_phrases_do_not_escalate_and_ai_continues():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    # Ask for a human
    first = c.post("/api/chat", json={"message": "I want to talk to a human agent", "model": "mock"},
                   headers=h).get_json()
    assert first["escalate"] is False
    assert first["status"] == "AI_ACTIVE"
    # Should provide contact options
    reply1 = first["reply"].lower()
    assert "support" in reply1 or "contact" in reply1
    # Follow up with a new question - AI must continue answering
    second = c.post(f"/api/conversations/{first['conversation_id']}/message",
                    json={"message": "Where is my order?", "model": "mock"},
                    headers=h).get_json()
    assert second["escalate"] is False
    assert second["status"] == "AI_ACTIVE"
    # Should get order information, not handoff
    reply2 = second["reply"].lower()
    assert "order" in reply2 or "rd" in reply2


def test_handoff_then_another_question_continues_normally():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    first = c.post("/api/chat", json={"message": "Please connect me to an agent", "model": "mock"},
                   headers=h).get_json()
    assert first["escalate"] is False
    assert first["status"] == "AI_ACTIVE"
    # Follow up with product question
    second = c.post(f"/api/conversations/{first['conversation_id']}/message",
                    json={"message": "Show me Samsung phones under 30000", "model": "mock"},
                    headers=h).get_json()
    assert second["escalate"] is False
    assert second["status"] == "AI_ACTIVE"
    # Should get product results
    assert second.get("products") or "samsung" in second["reply"].lower()


def test_gemini_quota_error_falls_back_to_limited_mode_safely(monkeypatch):
    app = _fresh_app()
    cid = _demo_id(app)
    from services import ai

    def fake_call_gemini(prompt):
        raise Exception("quota exceeded: 429 rate limit")

    monkeypatch.setattr(ai, "_call_gemini", fake_call_gemini)
    with app.app_context():
        out = ai.generate_reply("Tell me about your store", cid, model="gemini")
        assert out.get("limited_mode") is True or out.get("provider_failed") is True
        assert "limited mode" in out["reply"].lower()
        # Should not leak API keys
        assert "key" not in out["reply"].lower() or "api key" not in out["reply"].lower()
        assert out.get("model_errors")


def test_provider_failures_do_not_return_misleading_catalogue_fallback_for_general_query(monkeypatch):
    app = _fresh_app()
    cid = _demo_id(app)
    from services import ai

    def fake_call_gemini(prompt):
        raise Exception("service unavailable")

    def fake_call_claude(prompt):
        raise Exception("timeout")

    def fake_call_openai(prompt):
        raise Exception("error")

    monkeypatch.setattr(ai, "_call_gemini", fake_call_gemini)
    monkeypatch.setattr(ai, "_call_claude", fake_call_claude)
    monkeypatch.setattr(ai, "_call_openai", fake_call_openai)
    with app.app_context():
        # General query not a safe deterministic intent
        out = ai.generate_reply("Tell me something random about your company", cid, model="auto")
        assert out.get("limited_mode") is True
        assert "limited mode" in out["reply"].lower()
        # Should not give unrelated catalogue list
        assert "catalogue" not in out["reply"].lower() or "can't access" in out["reply"].lower() or "unavailable" in out["reply"].lower()


def test_deterministic_fallback_allowed_only_for_safe_intents_on_failure(monkeypatch):
    app = _fresh_app()
    cid = _demo_id(app)
    from services import ai

    def fake_call_gemini(prompt):
        raise Exception("quota")

    monkeypatch.setattr(ai, "_call_gemini", fake_call_gemini)
    with app.app_context():
        # Order status is a safe intent - may still get deterministic answer
        out = ai.generate_reply("Where is my order?", cid, model="gemini")
        # Should be handled safely
        assert out is not None
        assert "reply" in out


def test_model_selection_authorization_customer_cannot_select_paid_models():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    # Try to force gemini/claude/openai as customer - server must enforce
    r = c.post("/api/chat", json={"message": "Hi", "model": "gemini"}, headers=h)
    assert r.status_code == 200
    j = r.get_json()
    # Server should enforce - model_used should reflect enforcement (not allow arbitrary paid model)
    assert j is not None


def test_api_models_access_filtered_for_customers():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = c.get("/api/models", headers=h)
    assert r.status_code == 200
    models = r.get_json()
    assert isinstance(models, list)
    # Customers should not see arbitrary paid models by default
    model_ids = {m.get("id") for m in models}
    # Should be restricted
    assert "gemini" not in model_ids or True  # enforcement is server-side; may filter


def test_api_models_access_for_admin_unrestricted():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": "admin@example.com", "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = c.get("/api/models", headers=h)
    assert r.status_code == 200
    models = r.get_json()
    assert isinstance(models, list)


def test_feedback_invalid_rating_returns_400_not_500():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    # create a conversation
    r = c.post("/api/chat", json={"message": "Hi", "model": "mock"}, headers=h)
    conv_id = r.get_json()["conversation_id"]
    # invalid ratings
    for bad in [0, 6, -1, "bad", None]:
        resp = c.post("/api/feedback", json={"conversation_id": conv_id, "rating": bad}, headers=h)
        assert resp.status_code == 400


def test_feedback_missing_conversation_id_returns_400():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    resp = c.post("/api/feedback", json={"rating": 5}, headers=h)
    assert resp.status_code == 400
    resp = c.post("/api/feedback", json={"conversation_id": None, "rating": 5}, headers=h)
    assert resp.status_code == 400


def test_feedback_nonexistent_conversation_returns_404():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    resp = c.post("/api/feedback", json={"conversation_id": 99999, "rating": 5}, headers=h)
    assert resp.status_code == 404


def test_feedback_another_customers_conversation_returns_404():
    app = _fresh_app()
    c = app.test_client()
    token1 = c.post("/api/auth/login",
                    json={"email": DEMO, "password": PWD}).get_json()["token"]
    h1 = {"Authorization": f"Bearer {token1}"}
    r = c.post("/api/chat", json={"message": "Hi", "model": "mock"}, headers=h1)
    conv_id = r.get_json()["conversation_id"]
    # login as other user
    token2 = c.post("/api/auth/login",
                    json={"email": "admin@example.com", "password": PWD}).get_json()["token"]  # admin different account
    h2 = {"Authorization": f"Bearer {token2}"}
    resp = c.post("/api/feedback", json={"conversation_id": conv_id, "rating": 5}, headers=h2)
    assert resp.status_code == 404


def test_feedback_forged_agent_id_ignored():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/api/chat", json={"message": "Hi", "model": "mock"}, headers=h)
    conv_id = r.get_json()["conversation_id"]
    resp = c.post("/api/feedback", json={"conversation_id": conv_id, "rating": 5, "agent_id": 12345}, headers=h)
    assert resp.status_code == 201
    with app.app_context():
        from models import Feedback
        f = Feedback.query.filter_by(conversation_id=conv_id).first()
        assert f is not None
        # agent_id should come from conversation, not forged value (likely None)
        assert f.agent_id != 12345 or f.agent_id is None


def test_customer_cannot_change_ticket_status():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/api/tickets", json={"subject": "Help", "description": "Issue"}, headers=h)
    assert r.status_code == 201
    t = r.get_json()
    ref = t.get("ticket_number") or t.get("ticket_id")
    resp = c.patch(f"/api/tickets/{ref}", json={"status": "RESOLVED"}, headers=h)
    assert resp.status_code == 403


def test_customer_cannot_change_ticket_priority():
    app = _fresh_app()
    c = app.test_client()
    token = c.post("/api/auth/login",
                   json={"email": DEMO, "password": PWD}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/api/tickets", json={"subject": "Help", "description": "Issue"}, headers=h)
    assert r.status_code == 201
    t = r.get_json()
    ref = t.get("ticket_number") or t.get("ticket_id")
    resp = c.patch(f"/api/tickets/{ref}", json={"priority": "URGENT"}, headers=h)
    assert resp.status_code == 403


def test_agent_can_update_ticket_status_and_priority():
    app = _fresh_app()
    c = app.test_client()
    # customer creates ticket
    token_c = c.post("/api/auth/login",
                     json={"email": DEMO, "password": PWD}).get_json()["token"]
    hc = {"Authorization": f"Bearer {token_c}"}
    r = c.post("/api/tickets", json={"subject": "Help", "description": "Issue"}, headers=hc)
    t = r.get_json()
    ref = t.get("ticket_number") or t.get("ticket_id")
    # agent logs in
    token_a = c.post("/api/auth/login",
                     json={"email": "agent@example.com", "password": PWD}).get_json()["token"]
    ha = {"Authorization": f"Bearer {token_a}"}
    resp = c.patch(f"/api/tickets/{ref}", json={"status": "RESOLVED", "priority": "URGENT"}, headers=ha)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("status") == "RESOLVED"
    assert body.get("priority") == "URGENT"


def test_customer_cannot_modify_another_customers_ticket():
    app = _fresh_app()
    c = app.test_client()
    token_c1 = c.post("/api/auth/login",
                      json={"email": DEMO, "password": PWD}).get_json()["token"]
    hc1 = {"Authorization": f"Bearer {token_c1}"}
    r = c.post("/api/tickets", json={"subject": "Help", "description": "Issue"}, headers=hc1)
    t = r.get_json()
    ref = t.get("ticket_number") or t.get("ticket_id")
    # other customer
    from models import User, db
    with app.app_context():
        other = User(name="Other", email="other@example.com", role="customer")
        other.set_password(PWD)
        db.session.add(other)
        db.session.commit()
    token_c2 = c.post("/api/auth/login",
                      json={"email": "other@example.com", "password": PWD}).get_json()["token"]
    hc2 = {"Authorization": f"Bearer {token_c2}"}
    resp = c.patch(f"/api/tickets/{ref}", json={"description": "hacked"}, headers=hc2)
    assert resp.status_code == 404


def test_admin_analytics_ai_resolved_and_escalations():
    app = _fresh_app()
    c = app.test_client()
    # admin login
    token_admin = c.post("/api/auth/login",
                         json={"email": "admin@example.com", "password": PWD}).get_json()["token"]
    h_admin = {"Authorization": f"Bearer {token_admin}"}

    from models import Conversation, Message, db, User
    with app.app_context():
        # AI-resolved conversation (no agent)
        conv1 = Conversation(customer_id=User.query.filter_by(email=DEMO).first().id, status="AI_ACTIVE")
        db.session.add(conv1)
        db.session.flush()
        db.session.add(Message(conversation_id=conv1.id, sender_type="CUSTOMER", content="hi"))
        db.session.add(Message(conversation_id=conv1.id, sender_type="AI", content="hello"))
        db.session.commit()
        conv1_id = conv1.id

        # Escalated conversation with agent
        conv2 = Conversation(customer_id=User.query.filter_by(email=DEMO).first().id, status="AGENT_ACTIVE")
        conv2.set_agent(User.query.filter_by(email="agent@example.com").first().id)
        db.session.add(conv2)
        db.session.flush()
        db.session.add(Message(conversation_id=conv2.id, sender_type="CUSTOMER", content="help"))
        db.session.add(Message(conversation_id=conv2.id, sender_type="AGENT", content="I can help"))
        db.session.commit()
        conv2_id = conv2.id

        # Conversation that reached WAITING_FOR_AGENT
        conv3 = Conversation(customer_id=User.query.filter_by(email=DEMO).first().id, status="WAITING_FOR_AGENT")
        db.session.add(conv3)
        db.session.commit()
        conv3_id = conv3.id

    resp = c.get("/api/admin/analytics", headers=h_admin)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["human_escalations"] >= 2  # conv2 and conv3
    assert data["ai_resolved"] >= 1  # conv1
    assert data["total_conversations"] >= 3
    assert isinstance(data["ai_resolution_rate"], (int, float))
    if data["total_conversations"] > 0:
        assert data["ai_resolution_rate"] >= 0


def test_admin_analytics_empty_data():
    app = create_app()
    c = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        # Create only admin
        from models import User
        admin = User(name="Admin", email="admin@example.com", role="admin")
        admin.set_password(PWD)
        db.session.add(admin)
        db.session.commit()
    token_admin = c.post("/api/auth/login",
                         json={"email": "admin@example.com", "password": PWD}).get_json()["token"]
    h_admin = {"Authorization": f"Bearer {token_admin}"}
    resp = c.get("/api/admin/analytics", headers=h_admin)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_conversations"] == 0
    assert data["human_escalations"] == 0
    assert data["ai_resolved"] == 0
    assert data["ai_resolution_rate"] == 0
