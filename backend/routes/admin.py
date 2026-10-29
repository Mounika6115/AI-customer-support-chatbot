from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func
from models import db, User, Conversation, Ticket, Feedback, Message
admin_bp = Blueprint("admin", __name__)


@admin_bp.get("/analytics")
@jwt_required()
def analytics():
    if get_jwt().get("role") != "admin":
        return {"error": "Forbidden"}, 403

    total = Conversation.query.count()
    avg = db.session.query(func.avg(Feedback.rating)).scalar()

    # Count conversations that actually reached WAITING_FOR_AGENT (escalated to human)
    human_escalations = 0
    try:
        # Check if any conversation ever had status WAITING_FOR_AGENT
        # Also count by looking for SYSTEM message about agent joining or agent messages
        # Prefer counting distinct conversations that had WAITING_FOR_AGENT status at some point
        # or have agent messages / were assigned to agent
        # Since we don't have history table, use reliable signals:
        # 1. Conversations that went through WAITING_FOR_AGENT/AGENT_ACTIVE states
        # 2. Or have messages from AGENT sender
        escalated_conv_ids = set()
        # Conversations currently/completed that involved human agents
        for c in Conversation.query.all():
            # Check for agent messages
            if Message.query.filter_by(conversation_id=c.id, sender_type="AGENT").first():
                escalated_conv_ids.add(c.id)
                continue
            # Check for assignment to agent
            if c.effective_agent_id():
                escalated_conv_ids.add(c.id)
                continue
            # Check status history - if it was ever escalated
            if c.status in ("WAITING_FOR_AGENT", "AGENT_ACTIVE"):
                escalated_conv_ids.add(c.id)
                continue
        human_escalations = len(escalated_conv_ids)
    except Exception:
        human_escalations = 0

    # AI-resolved: conversations resolved/closed without an agent message
    ai_resolved = 0
    try:
        for c in Conversation.query.all():
            # Skip if it had agent involvement
            if Message.query.filter_by(conversation_id=c.id, sender_type="AGENT").first():
                continue
            if c.effective_agent_id():
                continue
            # Count if resolved/closed or just ended without escalation
            if c.status in ("RESOLVED", "CLOSED", "AI_ACTIVE"):
                # AI resolved means resolved without agent message
                ai_resolved += 1
    except Exception:
        ai_resolved = 0

    resolved = Conversation.query.filter_by(status="RESOLVED").count()

    # Calculate AI resolution rate from actual eligible conversations
    eligible = total
    if eligible > 0:
        ai_resolution_rate = round((ai_resolved / eligible) * 100.0, 2)
    else:
        ai_resolution_rate = 0.0

    mock_fallback_usage = None
    try:
        # Count conversations that used mock model
        mock_count = Message.query.filter(Message.ai_model.ilike("%mock%")).distinct(Message.conversation_id).count()
        mock_fallback_usage = {"conversations_with_mock": mock_count}
    except Exception:
        mock_fallback_usage = None

    result = {"total_customers": User.query.filter_by(role="customer").count(),
              "total_agents": User.query.filter_by(role="agent").count(),
              "total_conversations": total,
              "human_escalations": human_escalations,
              "ai_resolved": ai_resolved,
              "ai_resolution_rate": ai_resolution_rate,
              "open_tickets": Ticket.query.filter(Ticket.status.notin_(["RESOLVED", "CLOSED"])).count(),
              "resolved": resolved,
              "customer_satisfaction": round(avg or 0, 2)}
    if mock_fallback_usage is not None:
        result["mock_fallback_usage"] = mock_fallback_usage
    return result
