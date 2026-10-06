"""Relational schema for the Customer <-> AI Chatbot support platform.

Covers the required tables: users, product_categories, products,
orders, order_items, payments, returns, refunds, conversations, messages,
support_tickets, offers, warranties, notifications (+ knowledge base,
agent notes, feedback, evaluation results).

Works with SQLite (default, zero-config demo) and MySQL (production
preference) via DATABASE_URL, e.g.:
  mysql+pymysql://user:password@localhost:3306/supportdb

Legacy attribute names (User.role lowercase, Product.name, Order.product,
Message.content, Conversation.assigned_agent_id, Ticket) are preserved so
existing routes/tests keep working while the new spec-compliant columns
(product_name, order_number, message, agent_id, ticket_number, ...) are
the canonical fields going forward.
"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ---------------------------------------------------------------- users
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default="customer")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_password(self, p):
        self.password_hash = generate_password_hash(p)

    def check_password(self, p):
        try:
            return check_password_hash(self.password_hash, p)
        except Exception:
            return False

    @property
    def role_upper(self):
        return (self.role or "").upper()


# ---------------------------------------------------------------- agents
class Agent(db.Model):
    __tablename__ = "agents"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    agent_name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(80), nullable=False, default="General")
    status = db.Column(db.String(20), nullable=False, default="OFFLINE")  # ONLINE/OFFLINE/BUSY/AWAY
    availability = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])


# ---------------------------------------------------- product categories
class ProductCategory(db.Model):
    __tablename__ = "product_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# -------------------------------------------------------------- products
class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    # Spec-canonical fields
    product_name = db.Column(db.String(160), nullable=True, index=True)
    brand = db.Column(db.String(80), nullable=True, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("product_categories.id"), nullable=True, index=True)
    description = db.Column(db.Text, default="")
    price = db.Column(db.Float, nullable=False, default=0.0)
    original_price = db.Column(db.Float, nullable=True)
    discount = db.Column(db.Float, nullable=True, default=0.0)  # percent
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    rating = db.Column(db.Float, nullable=True, default=0.0)
    warranty_period = db.Column(db.String(100), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    specifications = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Legacy columns (kept for backward compatibility)
    name = db.Column(db.String(160), nullable=True)
    category = db.Column(db.String(60), nullable=True, index=True)
    availability = db.Column(db.Boolean, default=True)
    warranty = db.Column(db.String(100), nullable=True)
    return_policy = db.Column(db.Text, nullable=True)

    category_obj = db.relationship("ProductCategory", foreign_keys=[category_id])

    @property
    def display_name(self):
        return self.product_name or self.name or f"Product #{self.id}"

    @property
    def display_category(self):
        if self.category_obj is not None:
            return self.category_obj.name
        return self.category or ""

    @property
    def in_stock(self):
        if self.stock_quantity:
            return self.stock_quantity > 0
        return bool(self.availability)

    def to_dict(self):
        return {
            "id": self.id,
            "product_name": self.display_name,
            "name": self.display_name,
            "brand": self.brand or "",
            "category": self.display_category,
            "category_id": self.category_id,
            "description": self.description or "",
            "price": self.price,
            "original_price": self.original_price if self.original_price is not None else self.price,
            "discount": self.discount or 0,
            "stock_quantity": self.stock_quantity or 0,
            "in_stock": self.in_stock,
            "available": self.in_stock,
            "rating": self.rating or 0,
            "warranty_period": self.warranty_period or self.warranty or "",
            "warranty": self.warranty_period or self.warranty or "",
            "image_url": self.image_url or "",
            "specifications": self.specifications or "",
            "return_policy": self.return_policy or "30-day return",
        }


# ---------------------------------------------------------------- orders
class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(40), unique=True, nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    payment_status = db.Column(db.String(30), nullable=True, default="PENDING")
    order_status = db.Column(db.String(30), nullable=True, default="PLACED")
    delivery_address = db.Column(db.Text, nullable=True)
    expected_delivery_date = db.Column(db.String(20), nullable=True)
    tracking_number = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Legacy columns
    product = db.Column(db.String(160), nullable=True)
    quantity = db.Column(db.Integer, nullable=True, default=1)
    price = db.Column(db.Float, nullable=True)
    delivery_status = db.Column(db.String(40), nullable=True)
    order_date = db.Column(db.String(20), nullable=True)

    customer = db.relationship("User", foreign_keys=[customer_id])

    def to_dict(self):
        return {
            "id": self.id,
            "order_number": self.order_number or f"RD{100000 + (self.id or 0)}",
            "customer_id": self.customer_id,
            "total_amount": self.total_amount if self.total_amount else (self.price or 0),
            "payment_status": self.payment_status or "",
            "order_status": self.order_status or "",
            "delivery_status": self.delivery_status or self.order_status or "",
            "delivery_address": self.delivery_address or "",
            "expected_delivery_date": self.expected_delivery_date or "",
            "expected": self.expected_delivery_date or "",
            "tracking_number": self.tracking_number or "",
            "product": self.product or "",
            "status": self.order_status or "",
            "delivery": self.delivery_status or self.order_status or "",
            "expected": self.expected_delivery_date or "",
        }


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Float, nullable=False, default=0.0)  # unit price at order time

    order = db.relationship("Order", foreign_keys=[order_id], backref=db.backref("items", lazy="dynamic", cascade="all, delete-orphan"))
    product = db.relationship("Product", foreign_keys=[product_id])


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    method = db.Column(db.String(40), nullable=True, default="CARD")
    status = db.Column(db.String(30), nullable=False, default="PENDING")  # PENDING/PAID/FAILED/REFUNDED
    transaction_id = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReturnRequest(db.Model):
    __tablename__ = "returns"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    reason = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="REQUESTED")  # REQUESTED/APPROVED/PICKED_UP/RETURNED/REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Refund(db.Model):
    __tablename__ = "refunds"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    return_id = db.Column(db.Integer, db.ForeignKey("returns.id"), nullable=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(30), nullable=False, default="INITIATED")  # INITIATED/PROCESSING/COMPLETED/FAILED
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------- conversations
class Conversation(db.Model):
    __tablename__ = "conversations"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    status = db.Column(db.String(30), default="AI_ACTIVE", index=True)  # AI_ACTIVE/RESOLVED/CLOSED
    intent = db.Column(db.String(50), default="GENERAL_QUERY")
    sentiment = db.Column(db.String(20), default="Neutral")
    priority = db.Column(db.String(20), default="LOW")
    ai_summary = db.Column(db.Text, default="")
    assigned_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def effective_agent_id(self):
        return self.agent_id or self.assigned_agent_id

    def set_agent(self, agent_user_id):
        from datetime import datetime as _dt
        self.agent_id = agent_user_id
        self.assigned_agent_id = agent_user_id
        if self.assigned_at is None:
            self.assigned_at = _dt.utcnow()


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sender_type = db.Column(db.String(20), nullable=False, index=True)  # CUSTOMER/AI/AGENT/SYSTEM
    content = db.Column(db.Text, nullable=True)
    message = db.Column(db.Text, nullable=True)  # spec-canonical field (mirrors content)
    ai_model = db.Column(db.String(60), nullable=True)
    message_type = db.Column(db.String(20), nullable=False, default="TEXT")  # TEXT/PRODUCT/ORDER/SYSTEM/FILE/TICKET
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def text(self):
        return self.message or self.content or ""

    def to_dict(self):
        iso = self.created_at.isoformat() if self.created_at else ""
        return {
            "id": self.id,
            "sender": (self.sender_type or "").lower(),
            "sender_type": (self.sender_type or "").upper(),
            "content": self.text,
            "message": self.text,
            "ai_model": self.ai_model or "",
            "message_type": self.message_type or "TEXT",
            "time": iso,
            "created_at": iso,
        }


# ---------------------------------------------------------------- tickets
_ticket_counter = {"n": 10045}

class Ticket(db.Model):
    __tablename__ = "support_tickets"
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=True, index=True)  # e.g. TKT10045
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=True, index=True)
    subject = db.Column(db.String(200), nullable=False, default="Support request")
    issue = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(60), nullable=True)
    priority = db.Column(db.String(20), default="MEDIUM")
    status = db.Column(db.String(30), default="OPEN")  # OPEN/WAITING_FOR_AGENT/IN_PROGRESS/RESOLVED/CLOSED
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    resolution = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def ensure_number(self):
        if not self.ticket_number:
            # Derive from the DB (not a static counter) so backend restarts
            # never reuse a number that already exists.
            n = (db.session.query(db.func.max(Ticket.id)).scalar() or 0) + 1
            while Ticket.query.filter_by(ticket_number=f"TKT{10000 + n}").first():
                n += 1
            self.ticket_number = f"TKT{10000 + n}"
        if not self.issue and self.description:
            self.issue = self.description
        if not self.description and self.issue:
            self.description = self.issue

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_number or f"TKT{10000 + (self.id or 0)}",
            "ticket_number": self.ticket_number or f"TKT{10000 + (self.id or 0)}",
            "customer_id": self.customer_id,
            "conversation_id": self.conversation_id,
            "subject": self.subject,
            "issue": self.issue or self.description or self.subject,
            "description": self.description or self.issue or "",
            "priority": self.priority,
            "status": self.status,
        }


# ----------------------------------------------------------------- offers
class Offer(db.Model):
    __tablename__ = "offers"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    discount_percent = db.Column(db.Float, default=0.0)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("product_categories.id"), nullable=True)
    valid_from = db.Column(db.DateTime, nullable=True)
    valid_to = db.Column(db.DateTime, nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Warranty(db.Model):
    __tablename__ = "warranties"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    period = db.Column(db.String(100), nullable=False, default="1 year")
    status = db.Column(db.String(30), nullable=False, default="ACTIVE")
    expires_at = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False, default="")
    body = db.Column(db.Text, nullable=False, default="")
    kind = db.Column(db.String(40), nullable=False, default="INFO")
    read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class KnowledgeBase(db.Model):
    __tablename__ = "knowledge_base"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180))
    category = db.Column(db.String(60))
    content = db.Column(db.Text)


class AgentNote(db.Model):
    __tablename__ = "agent_notes"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Feedback(db.Model):
    __tablename__ = "feedback"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EvaluationResult(db.Model):
    __tablename__ = "evaluation_results"
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.String(50))
    category = db.Column(db.String(50))
    customer_input = db.Column(db.Text)
    expected = db.Column(db.Text)
    actual = db.Column(db.Text)
    passed = db.Column(db.Boolean)
    reason = db.Column(db.Text)
    response_ms = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ------------------------------------------------------- service / repair
_service_counter = {"n": 20010}


class ServiceRequest(db.Model):
    """Repair / installation / warranty service requests (post-sales support)."""
    __tablename__ = "service_requests"
    id = db.Column(db.Integer, primary_key=True)
    request_number = db.Column(db.String(20), unique=True, nullable=True, index=True)  # e.g. SRV20011
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True, index=True)
    issue_type = db.Column(db.String(60), nullable=False, default="REPAIR")  # REPAIR/INSTALLATION/WARRANTY/DAMAGED/DEFECTIVE
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="REQUESTED")  # REQUESTED/APPROVED/PICKUP_SCHEDULED/PICKED_UP/IN_REPAIR/REPAIRED/OUT_FOR_DELIVERY/RESOLVED/CANCELLED
    pickup_status = db.Column(db.String(40), nullable=True, default="NOT_SCHEDULED")
    delivery_status = db.Column(db.String(40), nullable=True, default="NOT_SCHEDULED")
    warranty_claim = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def ensure_number(self):
        if not self.request_number:
            # Derive from the DB (not a static counter) so backend restarts
            # never reuse a number that already exists.
            n = (db.session.query(db.func.max(ServiceRequest.id)).scalar() or 0) + 1
            while ServiceRequest.query.filter_by(request_number=f"SRV{20000 + n}").first():
                n += 1
            self.request_number = f"SRV{20000 + n}"

    def to_dict(self):
        return {
            "id": self.id,
            "request_number": self.request_number or f"SRV{20000 + (self.id or 0)}",
            "customer_id": self.customer_id,
            "order_id": self.order_id,
            "product_id": self.product_id,
            "issue_type": self.issue_type,
            "description": self.description or "",
            "status": self.status,
            "pickup_status": self.pickup_status or "NOT_SCHEDULED",
            "delivery_status": self.delivery_status or "NOT_SCHEDULED",
            "warranty_claim": bool(self.warranty_claim),
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }
