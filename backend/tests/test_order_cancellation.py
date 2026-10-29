"""Regression tests for order-cancellation eligibility and in-transit handling."""
import pytest

from app import create_app
from models import db, Order, Refund, User
from services import tools as T
from services.ai import generate_reply
from services.seed import seed

DEMO = "customer@example.com"


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


def _demo_order():
    return Order.query.filter_by(order_number="RD100234").first()


def _snapshot(order):
    return {
        "order_status": order.order_status,
        "delivery_status": order.delivery_status,
        "expected_delivery_date": order.expected_delivery_date,
        "payment_status": order.payment_status,
        "tracking_number": order.tracking_number,
        "refund_count": Refund.query.filter_by(order_id=order.id).count(),
    }


@pytest.mark.parametrize("status", ["PLACED", "CONFIRMED", "PROCESSING"])
def test_cancellation_allowed_for_pre_shipment_statuses(status):
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        order = _demo_order()
        order.order_status = status
        order.delivery_status = status
        order.expected_delivery_date = "2099-01-01"
        db.session.commit()

        res = T.cancel_order(order.order_number, cid)

        db.session.refresh(order)
        assert res["ok"] is True
        assert res["order_status"] == "CANCELLED"
        assert order.order_status == "CANCELLED"
        assert order.delivery_status == "CANCELLED"
        assert order.expected_delivery_date is None


@pytest.mark.parametrize(
    ("order_status", "delivery_status"),
    [
        ("SHIPPED", "SHIPPED"),
        ("SHIPPED", "OUT_FOR_DELIVERY"),
        ("OUT_FOR_DELIVERY", "OUT_FOR_DELIVERY"),
    ],
)
def test_in_transit_order_cancellation_is_rejected_without_db_changes(
        order_status, delivery_status):
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        order = _demo_order()
        order.order_status = order_status
        order.delivery_status = delivery_status
        db.session.commit()
        before = _snapshot(order)

        res = T.cancel_order(order.order_number, cid)

        db.session.refresh(order)
        assert res["ok"] is False
        assert res.get("reason") == "IN_TRANSIT"
        error = res["error"].lower()
        assert "on its way" in error
        assert "refuse delivery" in error
        assert "return the item after arrival" in error
        assert "30-day return window" in error
        assert "refund" not in error
        assert _snapshot(order) == before


@pytest.mark.parametrize(
    ("order_status", "delivery_status"),
    [
        ("SHIPPED", "OUT_FOR_DELIVERY"),
        ("OUT_FOR_DELIVERY", "OUT_FOR_DELIVERY"),
    ],
)
def test_in_transit_chat_reply_does_not_claim_success_or_refund(
        order_status, delivery_status):
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        order = _demo_order()
        order.order_status = order_status
        order.delivery_status = delivery_status
        db.session.commit()
        before = _snapshot(order)

        out = generate_reply(f"cancel my order {order.order_number}", cid, model="mock")

        db.session.refresh(order)
        reply = out["reply"].lower()
        assert out["action"]["type"] == "cancel_order"
        assert out["action"]["ok"] is False
        assert "on its way" in reply
        assert "refuse delivery" in reply
        assert "return the item after arrival" in reply
        assert "30-day return window" in reply
        assert "has been cancelled" not in reply
        assert "refund" not in reply
        assert "initiated" not in reply
        assert _snapshot(order) == before


@pytest.mark.parametrize("status", ["DELIVERED", "CANCELLED", "REFUND_COMPLETED"])
def test_terminal_order_statuses_remain_protected(status):
    app = _fresh_app()
    cid = _demo_id(app)
    with app.app_context():
        order = _demo_order()
        order.order_status = status
        order.delivery_status = status
        db.session.commit()
        before = _snapshot(order)

        res = T.cancel_order(order.order_number, cid)

        db.session.refresh(order)
        assert res["ok"] is False
        assert "cannot be cancelled" in res["error"].lower()
        assert _snapshot(order) == before
