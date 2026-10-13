"""Agent endpoints (AIRM-41 Phase 1): inbox, claim, view, reply.

All routes require a JWT whose role claim is exactly "agent".
Customers (and admins) receive 403 on every route here.
"""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from models import db, Conversation, Message

agent_bp = Blueprint("agent", __name__)


def _aid():
    return int(get_jwt_identity())


def _deny_non_agent():
    if get_jwt().get("role") != "agent":
        return {"error": "Forbidden: agents only"}, 403
    return None


def _emit(conversation_id, event="new_message"):
    try:
        from app import socketio
        socketio.emit(event, {"conversation_id": conversation_id},
                      to=f"conversation_{conversation_id}")
    except Exception:
        pass


@agent_bp.get("/queue")
@jwt_required()
def queue():
    denied = _deny_non_agent()
    if denied:
        return denied
    cs = (Conversation.query.filter_by(status="WAITING_FOR_AGENT")
          .order_by(Conversation.updated_at.desc()).all())
    return [{"id": c.id, "customer_id": c.customer_id, "intent": c.intent,
             "priority": c.priority, "status": c.status,
             "updated_at": c.updated_at.isoformat() if c.updated_at else ""} for c in cs]


@agent_bp.get("/conversations/<int:i>")
@jwt_required()
def conversation(i):
    denied = _deny_non_agent()
    if denied:
        return denied
    c = Conversation.query.filter_by(id=i).first_or_404()
    if c.status != "WAITING_FOR_AGENT" and c.effective_agent_id() != _aid():
        return {"error": "Forbidden"}, 403
    ms = (Message.query.filter_by(conversation_id=i)
          .order_by(Message.created_at, Message.id).all())
    return {"id": c.id, "customer_id": c.customer_id, "status": c.status,
            "assigned_agent_id": c.effective_agent_id(),
            "messages": [m.to_dict() for m in ms]}


@agent_bp.post("/conversations/<int:i>/claim")
@jwt_required()
def claim(i):
    denied = _deny_non_agent()
    if denied:
        return denied
    c = Conversation.query.filter_by(id=i).first_or_404()
    if c.status in ("RESOLVED", "CLOSED"):
        return {"error": f"Conversation is {c.status}"}, 400
    if c.effective_agent_id() is not None and c.effective_agent_id() != _aid():
        return {"error": "Already claimed by another agent"}, 409
    c.set_agent(_aid())
    c.status = "AGENT_ACTIVE"
    db.session.add(Message(conversation_id=c.id, sender_id=_aid(), sender_type="SYSTEM",
                           content="An agent has joined the conversation.",
                           message="An agent has joined the conversation.",
                           message_type="SYSTEM"))
    db.session.commit()
    _emit(c.id)
    return {"conversation_id": c.id, "status": c.status,
            "assigned_agent_id": c.effective_agent_id()}


@agent_bp.post("/conversations/<int:i>/reply")
@jwt_required()
def reply(i):
    denied = _deny_non_agent()
    if denied:
        return denied
    c = Conversation.query.filter_by(id=i).first_or_404()
    if c.status != "AGENT_ACTIVE" or c.effective_agent_id() != _aid():
        return {"error": "Claim the conversation before replying"}, 403
    d = request.get_json() or {}
    text = (d.get("message") or "").strip()
    if not text:
        return {"error": "Message cannot be empty"}, 400
    db.session.add(Message(conversation_id=c.id, sender_id=_aid(), sender_type="AGENT",
                           content=text, message=text, message_type="TEXT"))
    db.session.commit()
    _emit(c.id)
    return {"conversation_id": c.id, "status": c.status}
