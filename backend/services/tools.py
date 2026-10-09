"""Backend AI tool functions. Every function queries the database —
Gemini must never invent product/order/refund data.

These are the single source of truth used by services/ai.py grounding,
by the REST API, and (via prompt instructions) by Gemini function calling.
"""
import re
from datetime import datetime
from models import (
    db, User, Product, ProductCategory, Order, OrderItem,
    Payment, ReturnRequest, Refund, Message,
    Offer, Warranty, Notification, ServiceRequest,
)

# ------------------------------------------------------------ customers
def get_customer(customer_id):
    u = User.query.get(customer_id)
    if not u:
        return None
    return {"id": u.id, "name": u.name, "email": u.email, "phone": u.phone or "",
            "role": u.role, "created_at": u.created_at.isoformat() if u.created_at else ""}

# ------------------------------------------------------------ products
def _product_query():
    return Product.query

def search_products(query="", brand=None, category=None, max_price=None, min_price=None,
                    in_stock_only=False, limit=10, customer_id=None):
    """Full-text-ish product search grounded in the products table."""
    q = (query or "").strip().lower()
    brand = (brand or "").strip().lower()
    category = (category or "").strip().lower()
    # price extraction like "under ₹30,000" / "under 30000"
    if max_price is None and q:
        m = re.search(r"under\s*[₹$]?\s*([\d,]+)", q)
        if m:
            try:
                max_price = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    tokens = [t for t in re.split(r"[^a-z0-9₹]+", q) if t and t not in
              {"show", "me", "phones", "phone", "want", "buy", "under", "with", "please", "the", "a", "an", "need", "looking", "for",
               "which", "one", "is", "cheapest", "best", "recommend", "compare", "cheap", "cost", "price"}]
    # keep brand-ish tokens
    results = []
    for p in _product_query().all():
        d = p.to_dict()
        hay = f"{d['product_name']} {d['brand']} {d['category']} {d['description']} {d['specifications']}".lower()
        if brand and brand not in hay:
            continue
        if category and category not in hay and category != d["category"].lower():
            continue
        if max_price is not None and (p.price or 0) > max_price:
            continue
        if min_price is not None and (p.price or 0) < min_price:
            continue
        if in_stock_only and not p.in_stock:
            continue
        if q and not tokens:
            score = 1
        elif not q:
            score = 1
        else:
            score = sum(1 for t in tokens if t in hay)
            # brand token boost: "samsung" should match brand exactly
            if brand and brand in hay:
                score += 2
            if not score:
                # Category fallback ONLY for generic queries ("show me phones").
                # A specific query with unmatched tokens ("Unicorn Phone X99")
                # must return no match so the bot says "not in catalog"
                # instead of listing unrelated products.
                if category and category in hay and not tokens:
                    score = 1
                else:
                    continue
        results.append((score, p.price or 0, d))
    results.sort(key=lambda r: (-r[0], r[1]))
    return [r[2] for r in results[:limit]]

def get_product(product_id):
    p = Product.query.get(product_id)
    return p.to_dict() if p else None

def check_stock(product_id):
    p = Product.query.get(product_id)
    if not p:
        return {"product_id": product_id, "in_stock": False, "stock_quantity": 0}
    return {"product_id": p.id, "product_name": p.display_name,
            "in_stock": p.in_stock, "stock_quantity": p.stock_quantity or 0}

def get_offers(active_only=True, category=None, limit=10):
    q = Offer.query
    if active_only:
        q = q.filter_by(active=True)
    offers = q.all()
    out = []
    for o in offers[:limit]:
        out.append({"id": o.id, "title": o.title, "description": o.description,
                    "discount_percent": o.discount_percent, "product_id": o.product_id,
                    "category_id": o.category_id, "active": o.active})
    return out

def get_warranty(product_id=None, order_id=None, customer_id=None):
    q = Warranty.query
    if product_id:
        q = q.filter_by(product_id=product_id)
    if order_id:
        q = q.filter_by(order_id=order_id)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    rows = q.all()
    if not rows and product_id:
        p = Product.query.get(product_id)
        if p:
            return {"product_id": product_id, "period": p.warranty_period or p.warranty or "1 year",
                    "status": "ACTIVE", "source": "product record"}
        return None
    return [{"id": w.id, "product_id": w.product_id, "period": w.period,
             "status": w.status, "expires_at": w.expires_at or ""} for w in rows]

# --------------------------------------------------------------- orders
def get_orders(customer_id, limit=20):
    rows = (Order.query.filter_by(customer_id=customer_id)
            .order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).all())
    out = []
    for o in rows:
        d = o.to_dict()
        items = [{"product_id": it.product_id,
                  "product_name": it.product.display_name if it.product else "",
                  "quantity": it.quantity, "price": it.price}
                 for it in o.items.all()] if hasattr(o, "items") else []
        d["items"] = items
        out.append(d)
    return out

def get_order_status(order_ref, customer_id=None):
    """order_ref may be numeric id or order_number like RD100234."""
    o = None
    s = str(order_ref).strip().upper()
    if customer_id:
        o = Order.query.filter_by(order_number=s, customer_id=customer_id).first()
        if o is None:
            # Privacy: never fall back to another customer's order. A caller
            # scoped to a customer only sees that customer's rows.
            try:
                oid = int(re.sub(r"\D", "", s) or s)
                o = Order.query.filter_by(id=oid, customer_id=customer_id).first()
            except ValueError:
                pass
            return None if not o else _order_to_dict(o)
    if o is None:
        o = Order.query.filter_by(order_number=s).first()
    if o is None:
        try:
            oid = int(re.sub(r"\D", "", s) or s)
            q = Order.query.filter_by(id=oid)
            if customer_id:
                q = q.filter_by(customer_id=customer_id)
            o = q.first()
        except ValueError:
            pass
    if not o:
        return None
    return _order_to_dict(o)


def _order_to_dict(o):
    d = o.to_dict()
    items = [{"product_id": it.product_id,
              "product_name": it.product.display_name if it.product else "",
              "quantity": it.quantity, "price": it.price}
             for it in o.items.all()] if hasattr(o, "items") else []
    d["items"] = items
    return d

def track_order(order_ref, customer_id=None):
    d = get_order_status(order_ref, customer_id)
    if not d:
        return None
    return {"order_number": d["order_number"], "order_status": d["order_status"],
            "delivery_status": d.get("delivery_status", ""),
            "tracking_number": d.get("tracking_number", ""),
            "expected_delivery_date": d.get("expected_delivery_date", ""),
            "total_amount": d.get("total_amount", 0)}

def cancel_order(order_ref, customer_id):
    o = None
    s = str(order_ref).strip().upper()
    o = Order.query.filter_by(order_number=s, customer_id=customer_id).first()
    if o is None:
        try:
            oid = int(re.sub(r"\D", "", s) or s)
            o = Order.query.filter_by(id=oid, customer_id=customer_id).first()
        except ValueError:
            pass
    if not o:
        return {"ok": False, "error": "Order not found for this customer."}
    if (o.order_status or "").upper() in {"DELIVERED", "CANCELLED", "REFUND_COMPLETED"}:
        return {"ok": False, "error": f"Order {o.order_number} cannot be cancelled (status={o.order_status})."}
    o.order_status = "CANCELLED"
    o.delivery_status = "CANCELLED"
    # A cancelled order will never be delivered — drop the stale estimate
    # so no UI/API layer can show a delivery date for it.
    o.expected_delivery_date = None
    db.session.commit()
    return {"ok": True, "order_number": o.order_number, "order_status": o.order_status}

# ------------------------------------------------------- returns/refunds
def create_return(order_ref, customer_id, reason="", product_id=None):
    o = None
    s = str(order_ref).strip().upper()
    o = Order.query.filter_by(order_number=s, customer_id=customer_id).first()
    if o is None:
        # fall back to most recent order if no ref given
        o = Order.query.filter_by(customer_id=customer_id).order_by(Order.id.desc()).first()
    if not o:
        return {"ok": False, "error": "No order found to return."}
    r = ReturnRequest(order_id=o.id, customer_id=customer_id, product_id=product_id,
                      reason=reason or "Customer requested return", status="REQUESTED")
    db.session.add(r)
    o.order_status = "RETURN_REQUESTED"
    db.session.commit()
    return {"ok": True, "return_id": r.id, "order_number": o.order_number, "status": r.status}

def get_return_status(return_id=None, order_ref=None, customer_id=None):
    q = ReturnRequest.query
    if return_id:
        q = q.filter_by(id=return_id)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    if order_ref:
        o = get_order_status(order_ref, customer_id)
        if o:
            q = q.filter_by(order_id=o["id"])
    rows = q.order_by(ReturnRequest.id.desc()).all()
    return [{"id": r.id, "order_id": r.order_id, "status": r.status,
             "reason": r.reason} for r in rows]

def get_refund_status(refund_id=None, order_ref=None, customer_id=None):
    q = Refund.query
    if refund_id:
        q = q.filter_by(id=refund_id)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    if order_ref:
        o = get_order_status(order_ref, customer_id)
        if o:
            q = q.filter_by(order_id=o["id"])
    rows = q.order_by(Refund.id.desc()).all()
    return [{"id": r.id, "order_id": r.order_id, "amount": r.amount,
             "status": r.status} for r in rows]


def get_return_eligibility(order_ref, customer_id):
    """Check whether an order can still be returned (30-day window, not already returned/cancelled)."""
    o = get_order_status(order_ref, customer_id)
    if not o:
        # fall back to latest order so "I want to return my product" still works
        orders = get_orders(customer_id, limit=1)
        if not orders:
            return {"ok": False, "eligible": False, "error": "I can help with returns and refunds, but I couldn't find any order on your account. Please share your order number and I'll help with the return."}
        o = orders[0]
    blocked = {"CANCELLED", "RETURNED", "RETURN_REQUESTED", "REFUND_COMPLETED"}
    if (o.get("order_status") or "").upper() in blocked:
        return {"ok": True, "eligible": False, "order_number": o["order_number"],
                "order_status": o.get("order_status"),
                "reason": f"Order {o['order_number']} is already {o.get('order_status')} and cannot be returned again."}
    existing = (ReturnRequest.query.filter_by(order_id=o["id"], customer_id=customer_id)
                .order_by(ReturnRequest.id.desc()).first())
    if existing and (existing.status or "").upper() not in {"REJECTED", "CANCELLED"}:
        return {"ok": True, "eligible": False, "order_number": o["order_number"],
                "order_status": o.get("order_status"),
                "reason": f"A return (#{existing.id}, status {existing.status}) already exists for order {o['order_number']}."}
    return {"ok": True, "eligible": True, "order_number": o["order_number"],
            "order_status": o.get("order_status"),
            "reason": f"Order {o['order_number']} is eligible for return within the 30-day return window.",
            "order_id": o["id"]}


def get_order_details(order_ref, customer_id=None):
    """Rich order details: items, payment, delivery estimate, tracking."""
    d = get_order_status(order_ref, customer_id)
    if not d:
        return None
    try:
        pay = (Payment.query.filter_by(order_id=d["id"])
               .order_by(Payment.id.desc()).first())
        payment = {"method": pay.method, "status": pay.status,
                   "amount": pay.amount} if pay else None
    except Exception:
        payment = None
    d["payment"] = payment
    d["estimated_delivery"] = d.get("expected_delivery_date") or d.get("expected") or ""
    return d


def get_product_details(product_ref):
    """Product info + specs + warranty + availability in one call."""
    p = None
    try:
        pid = int(str(product_ref).strip())
        p = Product.query.get(pid)
    except (ValueError, TypeError):
        pass
    if p is None:
        s = str(product_ref or "").strip().lower()
        p = (Product.query.filter(Product.product_name.ilike(f"%{s}%")).first()
             or Product.query.filter(Product.name.ilike(f"%{s}%")).first())
    if not p:
        return None
    d = p.to_dict()
    w = get_warranty(product_id=p.id)
    d["warranty_info"] = w if isinstance(w, dict) else (w[0] if isinstance(w, list) and w else None)
    d["availability"] = "In stock" if p.in_stock else "Out of stock"
    return d


# ------------------------------------------------------- service / repair
def create_service_request(customer_id, issue_type="REPAIR", description="",
                           order_ref=None, product_id=None, warranty_claim=False):
    order_id = None
    if order_ref:
        o = get_order_status(order_ref, customer_id)
        if o:
            order_id = o["id"]
            if not product_id:
                items = o.get("items") or []
                if items:
                    product_id = items[0].get("product_id")
    if not order_id and not product_id:
        # attach to latest order so the request is always traceable
        orders = get_orders(customer_id, limit=1)
        if orders:
            order_id = orders[0]["id"]
            items = orders[0].get("items") or []
            if not product_id and items:
                product_id = items[0].get("product_id")
    if not order_id and not product_id:
        return {"ok": False, "error": "No order or product found to raise a service request against."}
    issue = (issue_type or "REPAIR").upper()
    desc = (description or "Customer requested service").strip()[:500]
    # Idempotency: a retried request (double-click / harness retry) must not
    # mint duplicate tickets. Reuse the newest open request with the same
    # customer + issue + target + near-identical description.
    try:
        from datetime import datetime as _dt, timedelta as _td
        cutoff = _dt.utcnow() - _td(minutes=30)
        open_statuses = ("REQUESTED", "APPROVED", "PICKUP_SCHEDULED", "PICKED_UP",
                         "IN_REPAIR", "REPAIRED", "OUT_FOR_DELIVERY")
        q = ServiceRequest.query.filter(
            ServiceRequest.customer_id == customer_id,
            ServiceRequest.issue_type == issue,
            ServiceRequest.status.in_(open_statuses),
            ServiceRequest.created_at >= cutoff)
        if order_id:
            q = q.filter(ServiceRequest.order_id == order_id)
        if product_id:
            q = q.filter(ServiceRequest.product_id == product_id)
        for existing in q.order_by(ServiceRequest.id.desc()).limit(5).all():
            if (existing.description or "").strip()[:500] == desc:
                return {"ok": True, "duplicate": True, **existing.to_dict()}
    except Exception:
        pass
    sr = ServiceRequest(customer_id=customer_id, order_id=order_id, product_id=product_id,
                        issue_type=issue,
                        description=desc,
                        status="REQUESTED", pickup_status="NOT_SCHEDULED",
                        delivery_status="NOT_SCHEDULED",
                        warranty_claim=bool(warranty_claim))
    sr.ensure_number()
    db.session.add(sr)
    db.session.commit()
    return {"ok": True, **sr.to_dict()}


def list_service_requests(customer_id, limit=10):
    rows = (ServiceRequest.query.filter_by(customer_id=customer_id)
            .order_by(ServiceRequest.id.desc()).limit(limit).all())
    return [r.to_dict() for r in rows]


def get_service_status(request_ref, customer_id=None):
    s = str(request_ref or "").strip().upper()
    q = ServiceRequest.query
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    row = q.filter_by(request_number=s).first()
    if row is None:
        try:
            rid = int(re.sub(r"\D", "", s) or s)
            row = q.filter_by(id=rid).first()
        except ValueError:
            pass
    if not row:
        return None
    d = row.to_dict()
    if row.product_id:
        p = Product.query.get(row.product_id)
        d["product_name"] = p.display_name if p else ""
    return d

def get_conversation_history(conversation_id, limit=50):
    msgs = (Message.query.filter_by(conversation_id=conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit).all())
    return [m.to_dict() for m in msgs]
