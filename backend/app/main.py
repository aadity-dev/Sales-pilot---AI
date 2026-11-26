from __future__ import annotations

import base64
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import connect, init_db, new_id, seed_demo_lead, utc_now
from .schemas import AppointmentCancel, AppointmentCreate, CallCreate, ChatRequest, GeminiConfigRequest, LeadCreate, TTSRequest
from .services.agent import create_call, get_evidence, get_lead, process_message
from .services.knowledge import ingest_directory, retrieve
from .services.local_llm import (
    active_llm_provider,
    answer_knowledge_base_query,
    get_gemini_model,
    is_gemini_configured,
    is_llm_configured,
    is_local_llm_reachable,
    verify_gemini_key,
)
from .services.scoring import score_lead
from .services.voice import (
    EmptySpeechError,
    VoiceConfigError,
    VoiceProcessingError,
    VoiceTimeoutError,
    is_stt_configured,
    is_tts_configured,
    synthesize_speech,
    transcribe_audio_bytes,
    voice_capabilities,
)

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_KNOWLEDGE_DIR = ROOT / "knowledge_base"
DEFAULT_DB_PATH = ROOT / "data" / "salespilot.db"
load_dotenv(ROOT / ".env")
INDIA_TZ = ZoneInfo("Asia/Kolkata")
AUDIO_SUFFIXES = {".webm", ".mp4", ".m4a", ".ogg", ".wav", ".mp3", ".flac"}


def normalize_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=INDIA_TZ)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return normalize_dt(value).isoformat(timespec="seconds")


def _validate_audio_upload(audio: UploadFile) -> None:
    ct = (audio.content_type or "").split(";")[0].strip().lower()
    suffix = Path(audio.filename or "").suffix.lower()
    if ct.startswith("audio/"):
        return
    if ct in {"", "application/octet-stream", "video/webm"} and suffix in AUDIO_SUFFIXES:
        return
    raise HTTPException(status_code=415, detail="Please upload an audio recording")


def _upsert_env_vars(env_path: Path, updates: dict[str, str | None]) -> None:
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    remaining = {k: (v.replace("\r", "").replace("\n", "") if isinstance(v, str) else None) for k, v in updates.items()}
    out_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched_key = None
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                matched_key = key
        if matched_key is not None:
            new_val = remaining.pop(matched_key)
            if new_val:
                out_lines.append(f"{matched_key}={new_val}")
        else:
            out_lines.append(line)
    for key, val in remaining.items():
        if val:
            out_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")


def create_app(
    db_path: str | Path | None = None,
    knowledge_dir: str | Path | None = None,
    env_path: str | Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_db(application.state.db_path)
        seed_demo_lead(application.state.db_path)
        ingest_directory(application.state.db_path, application.state.knowledge_dir)
        yield

    app = FastAPI(
        title="SalesPilot AI",
        version="0.2.0",
        description="Local-first, evidence-driven AI sales voice agent.",
        lifespan=lifespan,
    )
    app.state.db_path = Path(db_path or os.getenv("SALESPILOT_DB_PATH", DEFAULT_DB_PATH))
    app.state.knowledge_dir = Path(knowledge_dir or os.getenv("SALESPILOT_KNOWLEDGE_DIR", DEFAULT_KNOWLEDGE_DIR))
    app.state.env_path = Path(env_path or ROOT / ".env")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with connect(app.state.db_path) as conn:
            conn.execute("SELECT 1").fetchone()
            lead_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        stt_ok = is_stt_configured()
        tts_ok = is_tts_configured()
        llm_configured = bool(os.getenv("SALESPILOT_LOCAL_LLM_URL", "").strip())
        gemini_ok = is_gemini_configured()
        return {
            "status": "ok",
            "app": "SalesPilot AI",
            "mode": "local-first",
            "database": "connected",
            "leads": lead_count,
            "knowledge_chunks": chunk_count,
            "speech_to_text_configured": stt_ok,
            "text_to_speech_configured": tts_ok,
            "gemini_configured": gemini_ok,
            "gemini_model": get_gemini_model(),
            "llm_provider": active_llm_provider(),
            "local_llm_configured": llm_configured,
            "local_llm_reachable": is_local_llm_reachable() if llm_configured else False,
            "text_to_speech": "macOS native voice (say) + browser fallback" if tts_ok else "browser speechSynthesis",
            "live_browser_stt": "Local Whisper VAD stream + Web Speech API fallback",
        }

    @app.get("/api/dashboard/stats")
    def dashboard_stats() -> dict[str, Any]:
        with connect(app.state.db_path) as conn:
            leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            hot = conn.execute("SELECT COUNT(*) FROM leads WHERE status='hot'").fetchone()[0]
            warm = conn.execute("SELECT COUNT(*) FROM leads WHERE status='warm'").fetchone()[0]
            avg_score_row = conn.execute("SELECT AVG(score) FROM leads").fetchone()[0]
            avg_score = round(float(avg_score_row), 1) if avg_score_row is not None else 0.0
            booked = conn.execute("SELECT COUNT(*) FROM appointments WHERE status='booked'").fetchone()[0]
            calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            handoffs = conn.execute("SELECT COUNT(*) FROM calls WHERE handoff_required=1").fetchone()[0]
            top_reqs = [
                {"requirement": row["requirement"], "count": row["cnt"]}
                for row in conn.execute(
                    """SELECT requirement, COUNT(*) AS cnt FROM leads
                       WHERE requirement IS NOT NULL AND TRIM(requirement) != ''
                       GROUP BY LOWER(requirement) ORDER BY cnt DESC LIMIT 3"""
                ).fetchall()
            ]
            sent_rows = conn.execute(
                "SELECT sentiment, COUNT(*) AS cnt FROM calls GROUP BY sentiment"
            ).fetchall()
            sentiments = {"positive": 0, "neutral": 0, "negative": 0}
            for row in sent_rows:
                key = (row["sentiment"] or "neutral").lower()
                if key in sentiments:
                    sentiments[key] += row["cnt"]
        hot_rate_pct = round((hot / leads) * 100, 1) if leads else 0.0
        booking_rate_pct = round((booked / leads) * 100, 1) if leads else 0.0
        return {
            "total_leads": leads,
            "hot_leads": hot,
            "warm_leads": warm,
            "avg_score": avg_score,
            "hot_rate_pct": hot_rate_pct,
            "booking_rate_pct": booking_rate_pct,
            "appointments_booked": booked,
            "calls": calls,
            "human_handoffs": handoffs,
            "top_requirements": top_reqs,
            "sentiment_breakdown": sentiments,
        }

    @app.get("/api/leads")
    def list_leads() -> list[dict[str, Any]]:
        with connect(app.state.db_path) as conn:
            rows = conn.execute("SELECT * FROM leads ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/leads", status_code=201)
    def create_lead(payload: LeadCreate) -> dict[str, Any]:
        lead_id = new_id("lead")
        now = utc_now()
        with connect(app.state.db_path) as conn:
            conn.execute(
                """INSERT INTO leads (id, name, company, email, phone, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lead_id, payload.name.strip(), payload.company, payload.email, payload.phone, now, now),
            )
            return dict(conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())

    @app.get("/api/leads/{lead_id}")
    def lead_detail(lead_id: str) -> dict[str, Any]:
        with connect(app.state.db_path) as conn:
            lead = get_lead(conn, lead_id)
            if not lead:
                raise HTTPException(status_code=404, detail="Lead not found")
            evidence = get_evidence(conn, lead_id)
            calls = [dict(row) for row in conn.execute("SELECT * FROM calls WHERE lead_id=? ORDER BY started_at DESC", (lead_id,)).fetchall()]
            latest_messages: list[dict[str, Any]] = []
            if calls:
                latest_messages = [
                    dict(row)
                    for row in conn.execute("SELECT * FROM messages WHERE call_id=? ORDER BY created_at", (calls[0]["id"],)).fetchall()
                ]
            appointments = [dict(row) for row in conn.execute("SELECT * FROM appointments WHERE lead_id=? ORDER BY start_time DESC", (lead_id,)).fetchall()]
        score, status, breakdown = score_lead(lead)
        return {
            "lead": lead,
            "evidence": evidence,
            "calls": calls,
            "latest_messages": latest_messages,
            "appointments": appointments,
            "score_breakdown": breakdown,
            "score": score,
            "status": status,
        }

    @app.post("/api/calls", status_code=201)
    def start_call(payload: CallCreate) -> dict[str, Any]:
        try:
            return create_call(str(app.state.db_path), payload.lead_id, payload.language)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/agent/chat")
    def agent_chat(payload: ChatRequest) -> dict[str, Any]:
        try:
            return process_message(str(app.state.db_path), payload.lead_id, payload.message, payload.call_id, payload.language)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/calls/{call_id}")
    def call_detail(call_id: str) -> dict[str, Any]:
        with connect(app.state.db_path) as conn:
            call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
            if not call:
                raise HTTPException(status_code=404, detail="Call not found")
            messages = [dict(row) for row in conn.execute("SELECT * FROM messages WHERE call_id=? ORDER BY created_at", (call_id,)).fetchall()]
        return {"call": dict(call), "messages": messages}

    @app.get("/api/knowledge/documents")
    def knowledge_documents() -> dict[str, Any]:
        with connect(app.state.db_path) as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) AS chunks FROM knowledge_chunks GROUP BY source ORDER BY source"
            ).fetchall()
        return {"documents": [dict(row) for row in rows]}

    @app.get("/api/knowledge/search")
    def knowledge_search(q: str) -> dict[str, Any]:
        if not q.strip():
            raise HTTPException(status_code=422, detail="Search query cannot be empty")
        results = retrieve(app.state.db_path, q, limit=5)
        ai_answer: str | None = None
        ai_supported: bool | None = None
        ai_sources: list[str] = []
        ai_mode = "deterministic_local"

        if is_llm_configured():
            fallback_chunks: list[dict[str, Any]] = []
            if not results:
                with connect(app.state.db_path) as conn:
                    fallback_chunks = [
                        dict(r)
                        for r in conn.execute("SELECT id, source, content FROM knowledge_chunks").fetchall()
                    ]
            kb_res = answer_knowledge_base_query(q, results, fallback_chunks=fallback_chunks)
            if kb_res:
                ai_answer = kb_res["answer"]
                ai_supported = kb_res["supported"]
                ai_sources = kb_res["sources"]
                ai_mode = "gemini_assisted" if is_gemini_configured() else "local_model_assisted"
                if not results and ai_supported and ai_sources:
                    allowed = set(ai_sources)
                    results = [
                        {"id": c["id"], "source": c["source"], "content": c["content"], "score": 1.0}
                        for c in fallback_chunks
                        if c["source"] in allowed
                    ][:3]

        return {
            "query": q,
            "results": results,
            "ai_answer": ai_answer,
            "ai_supported": ai_supported,
            "ai_sources": ai_sources,
            "ai_mode": ai_mode,
        }

    @app.post("/api/knowledge/reload")
    def knowledge_reload() -> dict[str, Any]:
        count = ingest_directory(app.state.db_path, app.state.knowledge_dir)
        with connect(app.state.db_path) as conn:
            docs = [dict(r) for r in conn.execute("SELECT source, COUNT(*) AS chunks FROM knowledge_chunks GROUP BY source ORDER BY source").fetchall()]
        return {"status": "reloaded", "chunks": count, "documents": docs}

    @app.get("/api/appointments/availability")
    def appointment_availability(for_date: date) -> dict[str, Any]:
        if for_date < datetime.now(INDIA_TZ).date():
            raise HTTPException(status_code=422, detail="Cannot check availability for a past date")
        slots = []
        day_start = datetime.combine(for_date, time.min, tzinfo=INDIA_TZ).astimezone(timezone.utc)
        day_end = datetime.combine(for_date + timedelta(days=1), time.min, tzinfo=INDIA_TZ).astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        with connect(app.state.db_path) as conn:
            booked = conn.execute(
                """SELECT start_time, end_time FROM appointments
                   WHERE status='booked' AND start_time < ? AND end_time > ?""",
                (day_end.isoformat(timespec="seconds"), day_start.isoformat(timespec="seconds")),
            ).fetchall()
        booked_ranges = [(datetime.fromisoformat(row["start_time"]), datetime.fromisoformat(row["end_time"])) for row in booked]
        for hour in ([] if for_date.weekday() >= 5 else [10, 11, 12, 14, 15, 16]):
            local_start = datetime.combine(for_date, time(hour, 0), tzinfo=INDIA_TZ)
            start_utc = local_start.astimezone(timezone.utc)
            end_utc = start_utc + timedelta(minutes=30)
            if start_utc <= now_utc:
                continue
            conflict = any(start_utc < end and end_utc > start for start, end in booked_ranges)
            if not conflict:
                slots.append({"start_time": local_start.isoformat(), "label": local_start.strftime("%I:%M %p")})
        return {"date": for_date.isoformat(), "timezone": "Asia/Kolkata", "slots": slots}

    @app.get("/api/appointments")
    def list_appointments() -> list[dict[str, Any]]:
        with connect(app.state.db_path) as conn:
            rows = conn.execute(
                """SELECT a.*, l.name AS lead_name, l.company AS lead_company
                   FROM appointments a JOIN leads l ON l.id=a.lead_id
                   ORDER BY a.start_time"""
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/appointments", status_code=201)
    def book_appointment(payload: AppointmentCreate) -> dict[str, Any]:
        start = normalize_dt(payload.start_time)
        end = start + timedelta(minutes=payload.duration_minutes)
        if start <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Appointment must be in the future")
        start_text, end_text = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        with connect(app.state.db_path) as conn:
            if not conn.execute("SELECT 1 FROM leads WHERE id=?", (payload.lead_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Lead not found")
            if payload.idempotency_key:
                existing = conn.execute("SELECT * FROM appointments WHERE idempotency_key=?", (payload.idempotency_key,)).fetchone()
                if existing:
                    return {**dict(existing), "idempotent_replay": True}
            conflict = conn.execute(
                """SELECT id FROM appointments WHERE status='booked'
                   AND NOT (end_time <= ? OR start_time >= ?) LIMIT 1""",
                (start_text, end_text),
            ).fetchone()
            if conflict:
                raise HTTPException(status_code=409, detail="That appointment slot is no longer available")
            appointment_id = new_id("appt")
            conn.execute(
                """INSERT INTO appointments
                   (id, lead_id, start_time, end_time, status, idempotency_key, notes, created_at)
                   VALUES (?, ?, ?, ?, 'booked', ?, ?, ?)""",
                (appointment_id, payload.lead_id, start_text, end_text, payload.idempotency_key, payload.notes, utc_now()),
            )
            return dict(conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone())

    @app.post("/api/appointments/{appointment_id}/cancel")
    def cancel_appointment(appointment_id: str, payload: AppointmentCancel) -> dict[str, Any]:
        with connect(app.state.db_path) as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Appointment not found")
            conn.execute("UPDATE appointments SET status='cancelled', notes=? WHERE id=?", (payload.reason, appointment_id))
            return dict(conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone())

    @app.get("/api/voice/voices")
    def get_voices() -> dict[str, Any]:
        return voice_capabilities()

    @app.post("/api/voice/tts")
    def text_to_speech(payload: TTSRequest) -> Response:
        try:
            audio_bytes, voice_used = synthesize_speech(payload.text, voice=payload.voice, language=payload.language)
        except VoiceConfigError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except EmptySpeechError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except VoiceTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except VoiceProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=audio_bytes, media_type="audio/wav", headers={"X-Voice-Used": voice_used})

    @app.post("/api/voice/transcribe")
    async def transcribe_audio(
        audio: UploadFile = File(...),
        language: str = Form("auto"),
        allow_empty: bool = Form(False),
    ) -> dict[str, Any]:
        _validate_audio_upload(audio)
        content = await audio.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Audio file exceeds the 20 MB limit")
        try:
            transcript = transcribe_audio_bytes(content, audio.filename, audio.content_type, language)
            return {"transcript": transcript, "empty": False}
        except VoiceConfigError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except EmptySpeechError as exc:
            if allow_empty:
                return {"transcript": "", "empty": True}
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except VoiceTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except VoiceProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/voice/turn")
    async def voice_turn(
        audio: UploadFile = File(...),
        lead_id: str = Form(...),
        call_id: str | None = Form(None),
        language: str = Form("en-IN"),
        voice: str | None = Form(None),
        tts: bool = Form(True),
    ) -> dict[str, Any]:
        """Single-roundtrip voice turn: Whisper STT -> SalesPilot Agent -> Local TTS WAV."""
        _validate_audio_upload(audio)
        content = await audio.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Audio file exceeds the 20 MB limit")
        try:
            transcript = transcribe_audio_bytes(content, audio.filename, audio.content_type, language)
        except VoiceConfigError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except EmptySpeechError:
            return {"empty": True, "transcript": ""}
        except VoiceTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except VoiceProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            chat_result = process_message(str(app.state.db_path), lead_id, transcript, call_id or None, language)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        audio_b64: str | None = None
        voice_used: str | None = None
        if tts and is_tts_configured():
            try:
                tts_lang = chat_result.get("detected_language") or language
                wav_bytes, voice_used = synthesize_speech(
                    chat_result.get("spoken_response") or chat_result["response"],
                    voice=voice,
                    language=tts_lang,
                )
                audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
            except (VoiceConfigError, EmptySpeechError, VoiceTimeoutError, VoiceProcessingError):
                audio_b64 = None

        return {
            "empty": False,
            "transcript": transcript,
            "chat": chat_result,
            "audio_base64": audio_b64,
            "audio_mime": "audio/wav" if audio_b64 else None,
            "voice_used": voice_used,
        }

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        gemini_ok = is_gemini_configured()
        return {
            "local_first": True,
            "paid_api_required": False,
            "default_ai_mode": active_llm_provider() or "deterministic-local-workflow",
            "gemini_configured": gemini_ok,
            "gemini_model": get_gemini_model(),
            "stt": "whisper.cpp (local)" if is_stt_configured() else "whisper.cpp (optional local setup)",
            "live_browser_stt": "Continuous VAD + Whisper.cpp or Web Speech API",
            "tts": "macOS native voice (say) + browser speechSynthesis fallback" if is_tts_configured() else "browser speechSynthesis",
            "retrieval": "local TF-IDF lexical retrieval",
            "llm": f"Gemini ({get_gemini_model()}) active" if gemini_ok else "Optional Gemini API or local OpenAI-compatible endpoint",
        }

    @app.post("/api/settings/gemini")
    def configure_gemini(payload: GeminiConfigRequest) -> dict[str, Any]:
        clean_key = payload.api_key.strip()
        clean_model = payload.model.strip() or "gemini-3.1-flash-lite"
        if not clean_key:
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            _upsert_env_vars(app.state.env_path, {"GEMINI_API_KEY": None, "GOOGLE_API_KEY": None})
            return {
                "gemini_configured": False,
                "gemini_model": clean_model,
                "message": "Gemini API key cleared. Using deterministic local workflow.",
            }

        ok, msg = verify_gemini_key(clean_key, clean_model)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        os.environ["GEMINI_API_KEY"] = clean_key
        os.environ["GEMINI_MODEL"] = clean_model
        _upsert_env_vars(app.state.env_path, {"GEMINI_API_KEY": clean_key, "GEMINI_MODEL": clean_model})
        return {
            "gemini_configured": True,
            "gemini_model": clean_model,
            "message": msg,
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
