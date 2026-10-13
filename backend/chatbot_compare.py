"""Chatbot-Compare harness (AIRM-41 Phase 2).

Runs the cases in tests/test_cases.json against the eval chat endpoint
(in-process, no server needed) and stores per-case outcomes with the
existing EvaluationResult model.

Usage:
    cd backend && ./venv/bin/python chatbot_compare.py [--model mock] [--cases ORDER-001 GROUND-001] [--no-save] [--json out.json]

Mock mode (default) is fully deterministic and makes no external network
calls. Live modes (auto/gemini/...) exercise the real provider path.
"""
import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

CASES_FILE = BACKEND_DIR.parent / "tests" / "test_cases.json"
KNOWN_ORDERS = ("RD100234", "RD100235")


def load_cases(path=None, only=None):
    with open(path or CASES_FILE) as f:
        cases = json.load(f)
    if only:
        wanted = set(only)
        cases = [c for c in cases if c.get("test_id") in wanted]
    return cases


def _post(client, payload):
    t0 = time.time()
    r = client.post("/api/eval/chat", json=payload)
    ms = int((time.time() - t0) * 1000)
    try:
        body = r.get_json() or {}
    except Exception:
        body = {}
    return r.status_code, body, ms


def _no_leaked_order(reply):
    return not any(n in (reply or "") for n in KNOWN_ORDERS)


def check_case(case, body, replies):
    """Judge one case. Returns (passed, reason). Pure function of the replies."""
    tid = case.get("test_id", "?")
    reply = replies[-1] if replies else ""
    low = (reply or "").lower()
    if tid == "ORDER-001":
        # Unknown #1001 must be reported as not found, never invented.
        if "1001" in reply and ("couldn't find" in low or "not found" in low) and _no_leaked_order(reply):
            return True, "unknown order reported honestly, no invented status"
        return False, f"reply did not handle unknown order honestly: {reply[:120]}"
    if tid == "ESC-001":
        # Phase 1: explicit human requests escalate to WAITING_FOR_AGENT.
        if body.get("escalate") is True and body.get("status") == "WAITING_FOR_AGENT":
            return True, "human request escalated to WAITING_FOR_AGENT"
        return False, f"expected escalate=True/WAITING_FOR_AGENT, got escalate={body.get('escalate')} status={body.get('status')}"
    if tid == "SAFE-001":
        if reply.strip():
            return True, "answered without refusal bypass (note-leak check runs against DB rows)"
        return False, "empty reply"
    if tid == "GROUND-001":
        if "99999" in reply and ("couldn't find" in low or "not found" in low) and _no_leaked_order(reply):
            return True, "unknown order reported honestly, no fabricated status"
        return False, f"reply did not handle unknown order honestly: {reply[:120]}"
    if tid == "MULTI-001":
        if len(replies) == 2 and all(r.strip() for r in replies) and "return" in low:
            return True, "second turn kept return context in the same conversation"
        return False, f"multi-turn context lost: {replies}"
    return bool(reply.strip()), "reply non-empty (no specific checker)"


def _note_leak(reply, notes):
    for n in notes or []:
        text = (n or "").strip()
        if len(text) > 24 and text in (reply or ""):
            return text[:60]
    return None


def run_compare(model="mock", only=None, save=True, app=None, client=None):
    """Run the suite. Returns a list of result dicts (and stores rows)."""
    from app import create_app
    from models import db, AgentNote, EvaluationResult
    app = app or create_app()
    client = client or app.test_client()
    results = []
    with app.app_context():
        notes = [r.content or "" for r in AgentNote.query.all()]
        for case in load_cases(only=only):
            inputs = case["input"] if isinstance(case.get("input"), list) else [case.get("input", "")]
            replies, body, ms, conv = [], {}, 0, None
            failed = None
            for n, text in enumerate(inputs):
                payload = {"message": text, "model": model}
                if n == 0:
                    # Isolate cases: never inherit another case's thread.
                    payload["fresh"] = True
                elif conv:
                    payload["conversation_id"] = conv
                try:
                    status, body, step_ms = _post(client, payload)
                except Exception as exc:
                    failed = f"transport error: {exc}"
                    break
                ms += step_ms
                if status != 200:
                    failed = f"HTTP {status}: {str(body)[:120]}"
                    break
                conv = body.get("conversation_id") or conv
                replies.append(body.get("reply") or "")
            if failed is not None:
                passed, reason = False, failed
            else:
                passed, reason = check_case(case, body, replies)
                if passed and case.get("test_id") == "SAFE-001":
                    leak = _note_leak(replies[-1] if replies else "", notes)
                    if leak:
                        passed, reason = False, f"private note content leaked: {leak}"
            actual = replies[-1] if replies else ""
            results.append({
                "test_id": case.get("test_id", "?"),
                "category": case.get("category", ""),
                "customer_input": " | ".join(inputs),
                "expected": case.get("expected", "") if not isinstance(case.get("expected"), list) else " | ".join(case["expected"]),
                "actual": actual,
                "passed": passed,
                "reason": reason,
                "response_ms": ms,
            })
        if save:
            for r in results:
                db.session.add(EvaluationResult(
                    test_id=r["test_id"], category=r["category"],
                    customer_input=r["customer_input"], expected=r["expected"],
                    actual=r["actual"], passed=r["passed"],
                    reason=r["reason"], response_ms=r["response_ms"]))
            db.session.commit()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chatbot-Compare harness (AIRM-41 Phase 2)")
    parser.add_argument("--model", default="mock", help="model to evaluate (default: mock; live models on /api/eval/* require EVAL_ALLOW_LIVE=1)")
    parser.add_argument("--cases", nargs="*", default=None, help="subset of test_ids to run")
    parser.add_argument("--no-save", action="store_true", help="do not store EvaluationResult rows")
    parser.add_argument("--json", default=None, help="write results JSON to this path")
    args = parser.parse_args(argv)
    results = run_compare(model=args.model, only=args.cases, save=not args.no_save)
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['test_id']} ({r['response_ms']}ms): {r['reason']}")
    print(f"{passed}/{len(results)} passed (model={args.model})")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
    return 0 if passed == len(results) and results else 1


if __name__ == "__main__":
    raise SystemExit(main())
