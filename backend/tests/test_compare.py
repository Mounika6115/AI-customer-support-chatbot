EVAL_HEADERS = {"X-Eval-Key": "test-eval-key"}
"""AIRM-41 Phase 2: Chatbot-Compare harness regression tests (mock mode)."""
from app import create_app
from chatbot_compare import check_case, load_cases, run_compare
from models import db, EvaluationResult
from services.ai import generate_reply
from services.seed import seed


def _reset_db():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed()
    return app


def test_cases_file_has_expected_suite():
    cases = load_cases()
    assert {c["test_id"] for c in cases} == {"ORDER-001", "ESC-001", "SAFE-001", "GROUND-001", "MULTI-001"}


def test_harness_mock_suite_passes_and_stores():
    _reset_db()
    results = run_compare(model="mock", save=True)
    assert len(results) == 5
    assert all(r["passed"] for r in results), [r for r in results if not r["passed"]]
    for r in results:
        assert r["test_id"] and r["actual"] and r["response_ms"] >= 0
    app = create_app()
    with app.app_context():
        assert EvaluationResult.query.count() >= 5
        assert {r.test_id for r in EvaluationResult.query.all()} >= {"ORDER-001", "ESC-001", "GROUND-001"}


def test_results_endpoints_return_stored():
    _reset_db()
    run_compare(model="mock", save=True)
    app = create_app()
    c = app.test_client()
    rows = c.get("/api/eval/results", headers=EVAL_HEADERS).get_json()
    assert len(rows) >= 5
    assert {"ORDER-001", "ESC-001", "SAFE-001", "GROUND-001", "MULTI-001"} <= {r["test_id"] for r in rows}
    one = c.get("/api/eval/results/ORDER-001", headers=EVAL_HEADERS).get_json()
    assert len(one) >= 1 and all(r["test_id"] == "ORDER-001" for r in one)
    assert all("passed" in r and "actual" in r for r in rows)


def test_harness_makes_no_live_calls(monkeypatch):
    import services.ai as ai

    def _boom(*a, **k):
        raise AssertionError("live provider must not be called in mock mode")

    monkeypatch.setattr(ai, "_call_gemini", _boom)
    monkeypatch.setattr(ai, "_call_claude", _boom)
    monkeypatch.setattr(ai, "_call_openai", _boom)
    _reset_db()
    results = run_compare(model="mock", save=False)
    assert all(r["passed"] for r in results)


def test_general_query_unknown_ref_names_it():
    from models import User
    _reset_db()
    app = create_app()
    with app.app_context():
        cid = User.query.filter_by(email="customer@example.com").first().id
        out = generate_reply("Where is order #99999?", cid, model="mock")
        assert out["order"] is None
        assert "#99999" in out["reply"]
        assert "RD100234" not in out["reply"] and "RD100235" not in out["reply"]


def test_eval_fresh_isolates_threads():
    _reset_db()
    app = create_app()
    c = app.test_client()
    a = c.post("/api/eval/chat", json={"message": "Hi"}, headers=EVAL_HEADERS).get_json()["conversation_id"]
    b = c.post("/api/eval/chat", json={"message": "Hi"}, headers=EVAL_HEADERS).get_json()["conversation_id"]
    assert a == b  # default reuse keeps multi-turn memory
    n = c.post("/api/eval/chat", json={"message": "Hi", "fresh": True}, headers=EVAL_HEADERS).get_json()["conversation_id"]
    assert n not in (a, b)


def test_eval_forces_mock_without_opt_in(monkeypatch):
    import services.ai as ai

    def _boom(*a, **k):
        raise AssertionError("live provider must not be called")

    monkeypatch.setattr(ai, "_call_gemini", _boom)
    monkeypatch.setattr(ai, "_call_claude", _boom)
    monkeypatch.setattr(ai, "_call_openai", _boom)
    monkeypatch.delenv("EVAL_ALLOW_LIVE", raising=False)
    _reset_db()
    app = create_app()
    c = app.test_client()
    for model in ("gemini", "auto", "claude"):
        j = c.post("/api/eval/chat",
                   json={"message": "Show me Samsung phones under 30000", "model": model}, headers=EVAL_HEADERS).get_json()
        assert "mock" in j["model_used"], model
        assert "Galaxy" in j["reply"]


def test_eval_live_opt_in_preserved(monkeypatch):
    import services.ai as ai
    monkeypatch.setenv("EVAL_ALLOW_LIVE", "1")
    monkeypatch.setattr(ai, "_call_gemini", lambda prompt: ("Canned live.", "test-model", None))
    _reset_db()
    app = create_app()
    c = app.test_client()
    j = c.post("/api/eval/chat",
               json={"message": "Show me Samsung phones under 30000", "model": "gemini"}, headers=EVAL_HEADERS).get_json()
    assert j["model_used"] == "gemini:test-model"
    assert j["reply"] == "Canned live."
