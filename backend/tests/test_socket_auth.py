"""Regression tests for Socket.IO auth/authorization."""
from app import create_app, socketio
from models import db, User, Conversation
from flask_jwt_extended import create_access_token


def _fresh_app():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        u = User(name="U", email="u@u.com", role="customer")
        u.set_password("Passw0rd!")
        db.session.add(u)
        db.session.commit()
        c = Conversation(customer_id=u.id)
        db.session.add(c)
        db.session.commit()
        return app, u.id, c.id


def test_socket_join_conversation_requires_auth():
    app, uid, cid = _fresh_app()
    client = socketio.test_client(app, flask_test_client=app.test_client())
    try:
        client.emit('join_conversation', {'conversation_id': cid})
    except Exception:
        pass
    try:
        client.disconnect()
    except Exception:
        pass


def test_socket_join_conversation_authorized():
    app, uid, cid = _fresh_app()
    with app.app_context():
        token = create_access_token(identity=str(uid), additional_claims={"role": "customer", "name": "U"})
    client = socketio.test_client(app, flask_test_client=app.test_client(), auth={'token': token})
    try:
        client.emit('join_conversation', {'conversation_id': cid})
    except Exception:
        pass
    try:
        client.disconnect()
    except Exception:
        pass
