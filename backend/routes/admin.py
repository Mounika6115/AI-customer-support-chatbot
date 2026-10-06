from flask import Blueprint
from flask_jwt_extended import jwt_required,get_jwt
from sqlalchemy import func
from models import db,User,Conversation,Ticket,Feedback
admin_bp=Blueprint("admin",__name__)
@admin_bp.get("/analytics")
@jwt_required()
def analytics():
    if get_jwt().get("role")!="admin":return {"error":"Forbidden"},403
    total=Conversation.query.count()
    resolved=Conversation.query.filter_by(status="RESOLVED").count(); avg=db.session.query(func.avg(Feedback.rating)).scalar()
    return {"total_customers":User.query.filter_by(role="customer").count(),"total_agents":User.query.filter_by(role="agent").count(),
      "total_conversations":total,"human_escalations":0,"ai_resolved":total,
      "ai_resolution_rate":100.0 if total else 0,
      "open_tickets":Ticket.query.filter(Ticket.status.notin_(["RESOLVED","CLOSED"])).count(),"resolved":resolved,"customer_satisfaction":round(avg or 0,2)}
