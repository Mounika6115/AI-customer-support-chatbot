from app import create_app
from models import db, User
from services.ai import generate_reply


def test_general_query_gets_helpful_response():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="Test User", email="test@example.com", role="customer")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        result = generate_reply("How can I reset my password?", user.id)

        assert result["escalate"] is False
        reply = result["reply"].lower()
        assert "password" in reply or "reset" in reply or "login" in reply


def test_reply_uses_previous_chat_history():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="History User", email="history@example.com", role="customer")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        result = generate_reply(
            "My order is late again.",
            user.id,
            conversation_history=[
                {"role": "customer", "content": "I ordered a phone last week."},
                {"role": "ai", "content": "I can help track your order. Please share the order number."},
            ],
        )

        assert result["escalate"] is False
        assert "late" in result["reply"].lower() or "order" in result["reply"].lower() or "tracking" in result["reply"].lower()


def test_greeting_returns_helpful_response_without_escalation():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="Hello User", email="hello@example.com", role="customer")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        result = generate_reply("hi", user.id)

        assert result["escalate"] is False
        assert "help" in result["reply"].lower() or "hi" in result["reply"].lower() or "hello" in result["reply"].lower()


def test_refund_style_request_does_not_escalate_immediately():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="Refund User", email="refund@example.com", role="customer")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        result = generate_reply("can u return my money back", user.id)

        assert result["escalate"] is False
        assert "refund" in result["reply"].lower() or "money" in result["reply"].lower() or "help" in result["reply"].lower()


def test_gemini_placeholder_key_returns_clear_configuration_message(monkeypatch):
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name="Gemini User", email="gemini@example.com", role="customer")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        monkeypatch.setenv("AI_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")

        result = generate_reply("I want to know about my order status.", user.id)

        assert result["escalate"] is False
        # Customer-facing reply must stay clean (no config warnings); the
        # misconfiguration is reported in metadata instead.
        assert "gemini api key" not in result["reply"].lower()
        assert "mock" in result["model_used"]
        assert "warning" in result and "gemini" in result["warning"].lower()
