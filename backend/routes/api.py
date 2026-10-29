from datetime import datetime, timezone
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models import db, Conversation, Message, Ticket, Order, Feedback
from services.ai import generate_reply
from services import tools as T
import os

api_bp = Blueprint("api", __name__)


def _apply_rate_limit(limit_str):
    try:
        limiter = getattr(current_app, "limiter", None)
        if limiter is None:
            return lambda f: f
        from flask_limiter.util import get_remote_address
        return limiter.limit(limit_str, key_func=get_remote_address)
    except Exception:
        return lambda f: f



def cid():
    return int(get_jwt_identity())


def _get_user_role():
    try:
        claims = get_jwt()
        if claims:
            return (claims.get("role") or "").strip().lower()
    except Exception:
        pass
    return ""


def _is_admin():
    role = _get_user_role()
    return role == "admin"


def _allowed_models_for_customer():
    # Operator-configured allowlist via env var
    allowlist = os.getenv("CUSTOMER_ALLOWED_MODELS", "").strip()
    if allowlist:
        allowed = [m.strip().lower() for m in allowlist.split(",") if m.strip()]
        return set(allowed)
    # Default: only safe models for customers; admins can choose any
    return {"auto", "mock"}  # Restrictive default - customers cannot pick arbitrary paid models by default


def _enforce_model_selection(requested_model, is_admin_user=False):
    model = (requested_model or "auto").strip().lower()
    if is_admin_user:
        return model
    allowed = _allowed_models_for_customer()
    if model in allowed:
        return model
    # If not allowed, fall back to 'auto' (server-enforced)
    return "auto"


# Waiting-room notice shown (and stored) while a handoff is pending. Kept in
# one place so the API reply, the persisted SYSTEM message, and the dedup
# check always use identical text.
WAITING_NOTICE = ("Thanks — our support team has your messages and an agent "
                  "will reply here shortly.")


def _socket():
    try:
        from app import socketio
        return socketio
    except Exception:
        return None


def _emit(conversation_id, event="new_message"):
    s = _socket()
    if s is not None:
        try:
            s.emit(event, {"conversation_id": conversation_id}, to=f"conversation_{conversation_id}")
        except Exception:
            pass


@api_bp.post("/chat")
@jwt_required()
@_apply_rate_limit("20 per minute")
def chat():
    d = request.get_json() or {}
    text = (d.get("message") or "").strip()
    conversation_id = d.get("conversation_id")
    model = _enforce_model_selection(d.get("model"), is_admin_user=_is_admin())
    if not text:
        return {"error": "Message cannot be empty"}, 400
    if conversation_id:
        c = Conversation.query.filter_by(id=conversation_id, customer_id=cid()).first_or_404()
    else:
        # No id = the UI started a new chat (fresh state / "Start a new chat").
        # Always open a new conversation so old threads never leak into it.
        # Continuing a thread requires passing its conversation_id (or using
        # POST /conversations/<id>/message).
        c = Conversation(customer_id=cid())
        db.session.add(c)
        db.session.flush()
    return handle(c, text, model=model)


@api_bp.post("/conversations/<int:i>/message")
@jwt_required()
@_apply_rate_limit("30 per minute")
def message(i):
    c = Conversation.query.filter_by(id=i, customer_id=cid()).first_or_404()
    d = request.get_json() or {}
    model = _enforce_model_selection(d.get("model"), is_admin_user=_is_admin())
    return handle(c, (d.get("message") or "").strip(), model=model)


@api_bp.get("/models")
@jwt_required()
def models():
    from services.ai import list_models
    all_models = list_models()
    if _is_admin():
        return all_models
    allowed = _allowed_models_for_customer()
    # Filter models for non-admin customers
    filtered = []
    for m in all_models:
        mid = (m.get("id") or "").strip().lower()
        if mid in allowed:
            filtered.append(m)
    # If somehow empty, ensure at least auto/mock are present
    if not filtered:
        for m in all_models:
            mid = (m.get("id") or "").strip().lower()
            if mid in ("auto", "mock"):
                filtered.append(m)
    return filtered


def _save_msg(conversation_id, sender_id, sender_type, content, ai_model=None, message_type="TEXT"):
    st = (sender_type or "customer").upper()
    mt = (message_type or "TEXT").upper()
    m = Message(conversation_id=conversation_id, sender_id=sender_id, sender_type=st,
                content=content, message=content, ai_model=ai_model, message_type=mt)
    db.session.add(m)
    return m


def handle(c, text, model="auto"):
    if not text:
        return {"error": "Message cannot be empty"}, 400
    if c.status == "CLOSED":
        # Ended conversations stay ended (AIRM-46): never silently reopen.
        return {"error": "This conversation is closed. Start a new chat to continue."}, 400
    if c.status in ("WAITING_FOR_AGENT", "AGENT_ACTIVE"):
        # Pure-AI mode: always continue with AI answers even if previously escalated
        _save_msg(c.id, cid(), "CUSTOMER", text, message_type="TEXT")
        history = Message.query.filter_by(conversation_id=c.id).order_by(Message.created_at.asc()).all()
        history_data = [{"role": "customer" if m.sender_type == "CUSTOMER" else "ai",
                         "content": m.text} for m in history]
        out = generate_reply(text, cid(), conversation_history=history_data, model=model)
        c.intent = out["intent"]
        c.sentiment = out["sentiment"]
        c.priority = out["priority"]
        out["escalate"] = False
        c.status = "AI_ACTIVE"
        products = out.get("products") or []
        order = out.get("order")
        msg_type = "PRODUCT" if products else ("ORDER" if order else "TEXT")
        _save_msg(c.id, None, "AI", out["reply"],
                  ai_model=out.get("model_used") or "mock",
                  message_type=msg_type)
        db.session.commit()
        _emit(c.id)
        return {"conversation_id": c.id, "status": c.status, **out}
    _save_msg(c.id, cid(), "CUSTOMER", text, message_type="TEXT")
    history = Message.query.filter_by(conversation_id=c.id).order_by(Message.created_at.asc()).all()
    history_data = [{"role": "customer" if m.sender_type == "CUSTOMER" else "ai",
                     "content": m.text} for m in history]
    out = generate_reply(text, cid(), conversation_history=history_data, model=model)
    c.intent = out["intent"]
    c.sentiment = out["sentiment"]
    c.priority = out["priority"]
    # Pure-AI mode: never escalate to human agents
    out["escalate"] = False
    c.status = "AI_ACTIVE"
    products = out.get("products") or []
    order = out.get("order")
    msg_type = "PRODUCT" if products else ("ORDER" if order else "TEXT")
    _save_msg(c.id, None, "AI", out["reply"],
              ai_model=out.get("model_used") or "mock",
              message_type=msg_type)
    db.session.commit()
    _emit(c.id)
    return {"conversation_id": c.id, "status": c.status, **out}


@api_bp.get("/conversations")
@jwt_required()
def conversations():
    cs = Conversation.query.filter_by(customer_id=cid()).order_by(Conversation.updated_at.desc()).all()
    return [{"id": c.id, "status": c.status, "intent": c.intent, "priority": c.priority,
             "updated_at": c.updated_at.isoformat() if c.updated_at else ""} for c in cs]


@api_bp.get("/conversations/<int:i>")
@jwt_required()
def conversation(i):
    c = Conversation.query.filter_by(id=i, customer_id=cid()).first_or_404()
    ms = Message.query.filter_by(conversation_id=i).order_by(Message.created_at, Message.id).all()
    return {"id": c.id, "status": c.status,
            "messages": [m.to_dict() for m in ms]}


@api_bp.post("/conversations/<int:i>/close")
@jwt_required()
def close_conversation(i):
    """End a conversation (AIRM-46). Owner-only, idempotent: repeated closes
    return the CLOSED conversation. Other customers get 404."""
    from datetime import datetime as _dt
    c = Conversation.query.filter_by(id=i, customer_id=cid()).first_or_404()
    if c.status != "CLOSED":
        c.status = "CLOSED"
        c.closed_at = _dt.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
    return {"conversation_id": c.id, "status": c.status}


@api_bp.get("/tickets")
@jwt_required()
def tickets():
    xs = Ticket.query.filter_by(customer_id=cid()).order_by(Ticket.id.desc()).all()
    return [x.to_dict() for x in xs]


def _lookup_ticket(ref, customer_id, allow_staff=False):
    s = str(ref or "").strip().upper()
    if allow_staff:
        t = Ticket.query.filter_by(ticket_number=s).first()
        if t is None:
            try:
                tid = int("".join(ch for ch in s if ch.isdigit()) or s)
                if tid:
                    t = Ticket.query.filter_by(id=tid).first()
            except ValueError:
                pass
        if t is None and s.isdigit():
            try:
                t = Ticket.query.filter_by(id=int(s)).first()
            except Exception:
                pass
        return t
    t = Ticket.query.filter_by(ticket_number=s, customer_id=customer_id).first()
    if t is None:
        try:
            tid = int("".join(ch for ch in s if ch.isdigit()) or s)
            t = Ticket.query.filter_by(id=tid, customer_id=customer_id).first()
        except ValueError:
            pass
    if t is None and s.isdigit():
        try:
            t = Ticket.query.filter_by(id=int(s), customer_id=customer_id).first()
        except Exception:
            pass
    return t


@api_bp.get("/tickets/<ref>")
@jwt_required()
def ticket_detail(ref):
    t = _lookup_ticket(ref, cid())
    if not t:
        return {"error": "Ticket not found"}, 404
    return t.to_dict()


@api_bp.post("/tickets")
@jwt_required()
def ticket_create():
    d = request.get_json() or {}
    subject = (d.get("subject") or "").strip()
    description = (d.get("description") or d.get("issue") or "").strip()
    if not subject and not description:
        return {"error": "Subject or description is required"}, 400
    pri = (d.get("priority") or "MEDIUM").strip().upper()
    if pri not in ("LOW", "MEDIUM", "HIGH", "URGENT"):
        pri = "MEDIUM"
    conv_id = d.get("conversation_id")
    if conv_id:
        from models import Conversation as _C
        if not _C.query.filter_by(id=conv_id, customer_id=cid()).first():
            return {"error": "Conversation not found"}, 404
    t = Ticket(customer_id=cid(), conversation_id=conv_id,
               subject=subject or description[:80],
               description=description or subject,
               issue=description or subject,
               category=(d.get("category") or "GENERAL_QUERY").strip().upper()[:60] or "GENERAL_QUERY",
               priority=pri, status="OPEN")
    t.ensure_number()
    db.session.add(t)
    db.session.commit()
    return t.to_dict(), 201


@api_bp.patch("/tickets/<ref>")
@jwt_required()
def ticket_update(ref):
    role = _get_user_role()
    is_staff = role in ("agent", "admin")
    if is_staff:
        t = _lookup_ticket(ref, cid(), allow_staff=True)
        if not t:
            return {"error": "Ticket not found"}, 404
    else:
        t = _lookup_ticket(ref, cid(), allow_staff=False)
        if not t or t.customer_id != cid():
            return {"error": "Ticket not found"}, 404
    d = request.get_json() or {}
    if not is_staff:
        # Customers can only update permitted fields
        if "status" in d:
            return {"error": "Forbidden"}, 403
        if "priority" in d:
            return {"error": "Forbidden"}, 403
        if "subject" in d and str(d["subject"]).strip():
            t.subject = str(d["subject"]).strip()[:200]
        if "description" in d and str(d["description"]).strip():
            t.description = str(d["description"]).strip()
            t.issue = t.description
        if "category" in d and str(d["category"]).strip():
            # Allow customers to update category if desired, but not status/priority
            t.category = str(d["category"]).strip().upper()[:60]
        db.session.commit()
        return t.to_dict()
    # Staff can update more fields
    if "subject" in d and str(d["subject"]).strip():
        t.subject = str(d["subject"]).strip()[:200]
    if "description" in d and str(d["description"]).strip():
        t.description = str(d["description"]).strip()
        t.issue = t.description
    if "category" in d and str(d["category"]).strip():
        t.category = str(d["category"]).strip().upper()[:60]
    if "priority" in d:
        p = str(d["priority"] or "").strip().upper()
        if p not in ("LOW", "MEDIUM", "HIGH", "URGENT"):
            return {"error": "Priority must be LOW/MEDIUM/HIGH/URGENT"}, 400
        t.priority = p
    if "status" in d:
        s = str(d["status"] or "").strip().upper()
        if s not in ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"):
            return {"error": "Status must be OPEN/IN_PROGRESS/RESOLVED/CLOSED"}, 400
        t.status = s
    db.session.commit()
    return t.to_dict()


@api_bp.get("/orders")
@jwt_required()
def orders():
    return T.get_orders(cid())


@api_bp.get("/orders/<order_ref>")
@jwt_required()
def order(order_ref):
    try:
        oid = int(order_ref)
        o = Order.query.filter_by(id=oid, customer_id=cid()).first()
    except ValueError:
        o = None
    if o is None:
        d = T.get_order_status(order_ref, cid())
        if not d:
            return {"error": "Order not found"}, 404
        return d
    d = T.get_order_status(o.order_number or o.id, cid())
    return d or {"id": o.id, "product": o.product, "status": o.order_status,
                 "delivery": o.delivery_status, "expected": o.expected_delivery_date}


@api_bp.get("/products")
@jwt_required()
def products():
    q = (request.args.get("q") or "")
    brand = request.args.get("brand")
    category = request.args.get("category")
    max_price = request.args.get("max_price", type=float)
    min_price = request.args.get("min_price", type=float)
    in_stock = request.args.get("in_stock_only", type=int)
    return T.search_products(query=q, brand=brand, category=category,
                             max_price=max_price, min_price=min_price,
                             in_stock_only=bool(in_stock), limit=50)


@api_bp.get("/products/compare")
@jwt_required()
def products_compare():
    """Compare 2-4 products side-by-side: /api/products/compare?ids=1,2"""
    raw = (request.args.get("ids") or "").strip()
    ids = [int(x) for x in raw.replace(";", ",").split(",") if x.strip().isdigit()]
    ids = ids[:4]
    if len(ids) < 2:
        return {"error": "Pass at least 2 product ids, e.g. ?ids=1,2"}, 400
    out = []
    for pid in ids:
        d = T.get_product(pid)
        if not d:
            return {"error": f"Product {pid} not found"}, 404
        out.append(d)
    return out


@api_bp.get("/products/<int:pid>/similar")
@jwt_required()
def product_similar(pid):
    """Recommend similar alternatives: same category/brand, closest price, best rated."""
    limit = request.args.get("limit", default=4, type=int) or 4
    base = T.get_product(pid)
    if not base:
        return {"error": "Product not found"}, 404
    pool = T.search_products(query="", limit=100)
    ranked = []
    for p in pool:
        if p["id"] == pid:
            continue
        score = 0
        if p.get("category") and p.get("category") == base.get("category"):
            score += 3
        if p.get("brand") and base.get("brand") and p["brand"].lower() == (base["brand"] or "").lower():
            score += 2
        score += (p.get("rating") or 0) / 5.0
        try:
            price_gap = abs(float(p.get("price") or 0) - float(base.get("price") or 0))
            score -= price_gap / (float(base.get("price") or 1) + 1)
        except (TypeError, ValueError):
            pass
        ranked.append((score, p))
    ranked.sort(key=lambda r: -r[0])
    return [p for _, p in ranked[:max(1, min(limit, 10))]]


@api_bp.get("/products/<int:pid>")
@jwt_required()
def product_detail(pid):
    d = T.get_product(pid)
    if not d:
        return {"error": "Product not found"}, 404
    return d


@api_bp.get("/offers")
@jwt_required()
def offers():
    return T.get_offers()


@api_bp.post("/orders/<order_ref>/cancel")
@jwt_required()
def cancel(order_ref):
    res = T.cancel_order(order_ref, cid())
    if not res.get("ok"):
        return {"error": res.get("error")}, 400
    return res


@api_bp.post("/returns")
@jwt_required()
def create_return():
    d = request.get_json() or {}
    res = T.create_return(d.get("order_ref") or d.get("order_number") or "",
                          cid(), reason=d.get("reason", ""), product_id=d.get("product_id"))
    if not res.get("ok"):
        return {"error": res.get("error")}, 400
    return res, 201


@api_bp.get("/refunds")
@jwt_required()
def refunds():
    return T.get_refund_status(customer_id=cid())


@api_bp.get("/returns")
@jwt_required()
def returns():
    order_ref = request.args.get("order_ref") or request.args.get("order_number")
    return T.get_return_status(order_ref=order_ref, customer_id=cid())


@api_bp.get("/returns/eligibility/<order_ref>")
@jwt_required()
def return_eligibility(order_ref):
    return T.get_return_eligibility(order_ref, cid())


@api_bp.get("/orders/<order_ref>/details")
@jwt_required()
def order_details(order_ref):
    d = T.get_order_details(order_ref, cid())
    if not d:
        return {"error": "Order not found"}, 404
    return d


@api_bp.get("/service-requests")
@jwt_required()
def service_requests():
    return T.list_service_requests(cid())


@api_bp.post("/service-requests")
@jwt_required()
def create_service_request():
    d = request.get_json() or {}
    res = T.create_service_request(
        cid(), issue_type=d.get("issue_type", "REPAIR"),
        description=d.get("description", "") or d.get("issue", ""),
        order_ref=d.get("order_ref") or d.get("order_number"),
        product_id=d.get("product_id"),
        warranty_claim=bool(d.get("warranty_claim", False)))
    if not res.get("ok"):
        return {"error": res.get("error")}, 400
    return res, 201


@api_bp.get("/service-requests/<ref>")
@jwt_required()
def service_request_detail(ref):
    d = T.get_service_status(ref, cid())
    if not d:
        return {"error": "Service request not found"}, 404
    return d


@api_bp.get("/warranty")
@jwt_required()
def warranty():
    w = T.get_warranty(product_id=request.args.get("product_id", type=int),
                       order_id=request.args.get("order_id", type=int),
                       customer_id=cid())
    if isinstance(w, dict):
        return w
    if isinstance(w, list):
        return w
    # fall back to product-record warranty
    pid = request.args.get("product_id", type=int)
    if pid:
        p = T.get_product(pid)
        if p:
            return {"product_id": pid, "period": p.get("warranty_period") or p.get("warranty") or T.WARRANTY_DEFAULT_PERIOD,
                    "status": "ACTIVE", "source": "product record"}
    return []


@api_bp.post("/feedback")
@jwt_required()
def feedback():
    d = request.get_json() or {}
    if d.get("conversation_id") is None:
        return {"error": "conversation_id is required"}, 400
    try:
        conv_id = int(d.get("conversation_id"))
    except (TypeError, ValueError):
        return {"error": "conversation_id is required"}, 400
    c = Conversation.query.filter_by(id=conv_id).first()
    if not c or c.customer_id != cid():
        return {"error": "Conversation not found"}, 404
    rating = d.get("rating")
    try:
        rating_int = int(rating)
    except (TypeError, ValueError):
        return {"error": "Rating must be 1-5"}, 400
    if rating_int < 1 or rating_int > 5:
        return {"error": "Rating must be 1-5"}, 400
    agent_id = c.effective_agent_id() if hasattr(c, "effective_agent_id") else (c.agent_id or getattr(c, "assigned_agent_id", None))
    f = Feedback(conversation_id=conv_id, customer_id=cid(),
                 agent_id=agent_id, rating=rating_int, feedback=d.get("feedback"))
    db.session.add(f)
    db.session.commit()
    return {"message": "Thank you"}, 201
