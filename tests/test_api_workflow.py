from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def test_health_and_dashboard(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["mode"] == "local-first"
    stats = client.get("/api/dashboard/stats").json()
    assert stats["total_leads"] == 1  # seeded synthetic demo lead


def test_full_qualification_evidence_and_handoff_workflow(client):
    lead = client.post("/api/leads", json={"name": "Priya Sharma", "company": "Acme Systems"})
    assert lead.status_code == 201
    lead_id = lead.json()["id"]

    call = client.post("/api/calls", json={"lead_id": lead_id, "language": "en"})
    assert call.status_code == 201
    call_id = call.json()["id"]

    response = client.post("/api/agent/chat", json={
        "lead_id": lead_id,
        "call_id": call_id,
        "message": "We need customer support automation. Our budget is ₹50,000, we want to implement within 30 days, and I am the decision maker.",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["lead"]["score"] == 100
    assert payload["lead"]["status"] == "hot"
    assert payload["handoff_required"] is False
    evidence_fields = {item["field"] for item in payload["evidence"]}
    assert {"requirement", "budget_amount", "timeline_days", "decision_maker"}.issubset(evidence_fields)
    assert all(item["status"] == "verified" for item in payload["evidence"])

    detail = client.get(f"/api/leads/{lead_id}").json()
    assert detail["score"] == 100
    assert len(detail["evidence"]) >= 4

    handoff = client.post("/api/agent/chat", json={
        "lead_id": lead_id,
        "call_id": call_id,
        "message": "I am frustrated and want to talk to a human sales representative.",
    })
    assert handoff.status_code == 200
    assert handoff.json()["handoff_required"] is True
    assert handoff.json()["sentiment"] == "negative"


def test_rag_returns_source_and_does_not_invent_missing_answer(client):
    lead_id = client.get("/api/leads").json()[0]["id"]
    answer = client.post("/api/agent/chat", json={
        "lead_id": lead_id,
        "message": "Does your product integrate with Shopify?",
    })
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["citations"]
    assert payload["citations"][0]["source"] == "product.md"
    assert "does not confirm" in payload["response"].lower()

    missing = client.post("/api/agent/chat", json={
        "lead_id": lead_id,
        "message": "What is your certified satellite launch capability?",
    })
    assert missing.status_code == 200
    assert missing.json()["handoff_required"] is True
    assert missing.json()["citations"] == []


def test_appointment_booking_conflict_and_idempotency(client):
    lead_id = client.get("/api/leads").json()[0]["id"]
    future_day = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=3)).date()
    start = datetime.combine(future_day, datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")).replace(hour=10)
    start_iso = start.isoformat()
    request = {
        "lead_id": lead_id,
        "start_time": start_iso,
        "duration_minutes": 30,
        "notes": "Prototype demo",
        "idempotency_key": f"test-{lead_id}-{start_iso}",
    }
    first = client.post("/api/appointments", json=request)
    assert first.status_code == 201
    appointment_id = first.json()["id"]

    replay = client.post("/api/appointments", json=request)
    assert replay.status_code == 201
    assert replay.json()["id"] == appointment_id
    assert replay.json()["idempotent_replay"] is True

    availability = client.get(f"/api/appointments/availability?for_date={future_day.isoformat()}")
    assert availability.status_code == 200
    assert all(slot["start_time"] != start_iso for slot in availability.json()["slots"])

    conflict = client.post("/api/appointments", json={
        "lead_id": lead_id,
        "start_time": start_iso,
        "duration_minutes": 30,
        "idempotency_key": "another-request",
    })
    assert conflict.status_code == 409

    cancelled = client.post(f"/api/appointments/{appointment_id}/cancel", json={"reason": "Customer rescheduled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_static_dashboard_and_docs_are_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "SalesPilot" in page.text
    docs = client.get("/docs")
    assert docs.status_code == 200


def test_voice_transcription_is_explicitly_optional(client, monkeypatch):
    monkeypatch.delenv("WHISPER_CPP_BIN", raising=False)
    monkeypatch.delenv("WHISPER_MODEL_PATH", raising=False)
    response = client.post("/api/voice/transcribe", files={"audio": ("test.wav", b"not-a-real-audio", "audio/wav")})
    assert response.status_code == 501
    assert "whisper.cpp" in response.json()["detail"].lower()

    lead_id = client.get("/api/leads").json()[0]["id"]
    turn = client.post(
        "/api/voice/turn",
        data={"lead_id": lead_id},
        files={"audio": ("test.webm", b"not-a-real-audio", "audio/webm")},
    )
    assert turn.status_code == 501


def test_conversational_demo_booking_and_knowledge_documents(client):
    docs = client.get("/api/knowledge/documents")
    assert docs.status_code == 200
    assert docs.json()["documents"][0]["source"] == "product.md"

    voices = client.get("/api/voice/voices")
    assert voices.status_code == 200
    assert "stt_configured" in voices.json()

    lead_id = client.get("/api/leads").json()[0]["id"]
    # Pick next weekday dynamically so weekend doesn't cause "no slots"
    future_day = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).date()
    while future_day.weekday() >= 5:
        future_day += timedelta(days=1)

    reply = client.post("/api/agent/chat", json={
        "lead_id": lead_id,
        "message": f"Please book a demo for {future_day.isoformat()} at 11 AM",
    })
    assert reply.status_code == 200
    payload = reply.json()
    assert payload["appointment_booked"] is not None
    assert payload["appointment_booked"]["status"] == "booked"
    assert "11:00 am" in payload["response"].lower()

    detail = client.get(f"/api/leads/{lead_id}").json()
    assert len(detail["appointments"]) >= 1


def test_gemini_configuration_and_chat_workflow(client, monkeypatch):
    import json

    class FakeResp:
        def __init__(self, body: dict):
            self._data = json.dumps(body).encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=10.0):
        req_body = json.loads(req.data.decode("utf-8"))
        if req_body.get("contents", [{}])[0].get("parts", [{}])[0].get("text") == "Reply with OK":
            return FakeResp({"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})
        return FakeResp({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "answer": "Great, half a lakh works! When do you want to launch?",
                            "facts": [
                                {"field": "requirement", "value": "WhatsApp order support", "quote": "WhatsApp order support"},
                                {"field": "budget_amount", "value": 50000, "quote": "half a lakh"},
                            ],
                        })
                    }]
                }
            }]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    saved = client.post("/api/settings/gemini", json={"api_key": "AQ.fake-key", "model": "gemini-3.1-flash-lite"})
    assert saved.status_code == 200
    assert saved.json()["gemini_configured"] is True

    health = client.get("/api/health").json()
    assert health["gemini_configured"] is True
    assert health["gemini_model"] == "gemini-3.1-flash-lite"

    lead_id = client.post("/api/leads", json={"name": "Meera Nair"}).json()["id"]
    chat = client.post("/api/agent/chat", json={
        "lead_id": lead_id,
        "message": "We handle WhatsApp order support and can spend half a lakh.",
    })
    assert chat.status_code == 200
    payload = chat.json()
    assert payload["response_mode"] == "gemini_assisted"
    assert payload["lead"]["score"] == 50  # 25 requirement + 25 budget (deterministic!)
    assert payload["lead"]["status"] == "warm"

    cleared = client.post("/api/settings/gemini", json={"api_key": "", "model": "gemini-3.1-flash-lite"})
    assert cleared.status_code == 200
    assert cleared.json()["gemini_configured"] is False
