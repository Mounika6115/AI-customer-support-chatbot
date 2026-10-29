"""After-sales regression tests: warranty, refunds, returns, service, orders."""
from datetime import date, timedelta

from app import create_app
from models import (
    db, User, Order, Refund, ReturnRequest, Product, ServiceRequest, Warranty,
)
from services import tools as T
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


def _token(c, email=DEMO):
    return c.post("/api/auth/login",
                  json={"email": email, "password": PWD}).get_json()["token"]


# ---------------- warranty ----------------

def test_warranty_uses_catalog_and_order_records():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("What is the warranty of the AeroBook 14?",
                             cid, model="mock")
        assert out["action"]["type"] == "warranty_info"
        assert "2 years" in out["reply"]

        out = generate_reply("What is the warranty for order RD100234?",
                             cid, model="mock")
        assert out["action"]["type"] == "warranty_info"
        assert "RD100234" in out["reply"]
        assert "1 year" in out["reply"]


def test_expired_warranty_record_is_reported_as_expired():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        product = Product.query.filter(Product.product_name.ilike("%AeroBook%")).first()
        db.session.add(Warranty(
            product_id=product.id, customer_id=cid, period="2 years",
            status="EXPIRED",
            expires_at=(date.today() - timedelta(days=30)).isoformat()))
        db.session.commit()

        out = generate_reply("Is the AeroBook warranty still active?",
                             cid, model="mock")
        assert out["action"]["type"] == "warranty_info"
        assert "EXPIRED" in out["reply"]
        assert "2 years" in out["reply"]


def test_warranty_claim_returns_ticket_number_and_is_idempotent():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        msg = "I want to raise a warranty claim for my Pulse Pro"
        before = ServiceRequest.query.count()
        first = generate_reply(msg, cid, model="mock")
        second = generate_reply(msg, cid, model="mock")

        assert first["action"]["type"] == "service_request"
        assert first["action"]["issue_type"] == "WARRANTY"
        number = first["action"]["request_number"]
        assert number.startswith("SRV")
        assert number in first["reply"]
        assert "1 year" in first["reply"]

        assert second["action"]["request_number"] == number
        assert second["action"]["duplicate"] is True
        assert ServiceRequest.query.count() == before + 1
        assert T.get_service_status(number, cid) is not None


# ---------------- refunds ----------------

def test_refund_status_respects_explicit_order_reference():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        first_order = Order.query.filter_by(order_number="RD100234").first()
        second_order = Order.query.filter_by(order_number="RD100235").first()
        db.session.add(Refund(order_id=second_order.id, customer_id=cid,
                              amount=149.0, status="COMPLETED",
                              reason="unrelated newer refund"))
        db.session.commit()

        out = generate_reply("What is the refund status for order RD100234?",
                             cid, model="mock")
        assert out["action"]["type"] == "refund_status"
        assert out["action"]["refund"]["order_id"] == first_order.id
        assert "699" in out["reply"]
        assert "PROCESSING" in out["reply"]
        assert "149" not in out["reply"]


def test_refund_status_for_order_without_refund_does_not_use_other_order():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply(
            "When will I get my refund for order RD100235?", cid, model="mock")
        assert out["action"]["type"] == "refund_status"
        assert out["action"]["ok"] is False
        assert "RD100235" in out["reply"]
        assert "No refund record yet" in out["reply"]


# ---------------- returns ----------------

def test_create_return_helper_prevents_duplicates():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        first = T.create_return("RD100235", cid, reason="wrong size")
        second = T.create_return("RD100235", cid, reason="wrong size, retry")

        order = Order.query.filter_by(order_number="RD100235").first()
        assert first["ok"] is True
        assert first.get("duplicate") is not True
        assert second["ok"] is True
        assert second["duplicate"] is True
        assert second["return_id"] == first["return_id"]
        assert ReturnRequest.query.filter_by(order_id=order.id).count() == 1


def test_create_return_api_prevents_duplicates():
    app = _fresh_app()
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c)}"}

    first = c.post("/api/returns", json={"order_ref": "RD100235",
                                        "reason": "wrong size"}, headers=h)
    second = c.post("/api/returns", json={"order_ref": "RD100235",
                                         "reason": "double click"}, headers=h)

    assert first.status_code == 201
    assert second.get_json()["duplicate"] is True
    with app.app_context():
        assert ReturnRequest.query.count() == 1


# ---------------- service tickets / order follow-ups / escalation ----------------

def test_service_request_ticket_number_is_persisted():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        out = generate_reply("My Pulse Pro is broken, please repair it",
                             cid, model="mock")
        number = out["action"]["request_number"]
        assert number.startswith("SRV")
        assert number in out["reply"]
        stored = T.get_service_status(number, cid)
        assert stored is not None
        assert stored["request_number"] == number


def test_order_followups_use_conversation_memory():
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        history = [
            {"role": "customer", "content": "Where is my order RD100234?"},
            {"role": "ai", "content": "Order RD100234: status SHIPPED."},
        ]
        for msg in ("When will it arrive?", "Has it been delivered?",
                    "Has my order been delivered?"):
            out = generate_reply(msg, cid, conversation_history=history,
                                 model="mock")
            assert "RD100234" in out["reply"], msg

        out = generate_reply("What did I order?", cid,
                             conversation_history=history, model="mock")
        assert "RD100234" in out["reply"]
        assert "Nova X1" in out["reply"]


def test_after_sales_escalation_has_no_side_effects():
    app = _fresh_app()
    cid = _demo_id(app)
    c = app.test_client()
    h = {"Authorization": f"Bearer {_token(c)}"}
    with app.app_context():
        before = (
            ReturnRequest.query.count(),
            Refund.query.count(),
            len(T.list_service_requests(cid, limit=100)),
        )

    response = c.post("/api/chat",
                      json={"message": "I want to talk to a human about my refund"},
                      headers=h)

    body = response.get_json()
    assert body["escalate"] is False
    assert body["status"] == "AI_ACTIVE"
    with app.app_context():
        after = (
            ReturnRequest.query.count(),
            Refund.query.count(),
            len(T.list_service_requests(cid, limit=100)),
        )
    assert after == before
