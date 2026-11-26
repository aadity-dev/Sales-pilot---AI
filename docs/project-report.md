# SalesPilot AI — One-Page Project Report

**Project:** SalesPilot AI (`v0.2.0 MVP`) · **Repository:** `aadity-dev/Sales-pilot---AI` · **Date:** 26 November 2026  
**Stack:** Python 3.15, FastAPI, SQLite, Vanilla JS/Canvas (Web Audio API), Whisper.cpp + FFmpeg, macOS `say` / Web Speech API, Google Gemini (`gemini-3.1-flash-lite`)

---

## 1. Executive Summary & Problem Solved

Inbound sales teams lose qualified leads when slow follow-ups, ungrounded AI chatbots, or opaque CRM scores create manual work and mistrust. **SalesPilot AI** is an evidence-driven, local-first **live voice sales agent** that conducts natural two-way English and Hinglish calls, extracts verifiable customer facts linked verbatim to transcript quotes, computes a deterministic `0–100` qualification score, answers product questions strictly from approved local documents, books conflict-checked demo slots, and escalates unsupported or negative-sentiment calls to human reps.

---

## 2. Core Architecture & Design Principles

| Layer | Implementation | Key Design Principle |
|---|---|---|
| **Live Voice Studio** | `index.html`, `styles.css`, `app.js` | Persistent echo-cancelled mic + adaptive VAD turns (`LISTENING → THINKING → SPEAKING → LISTENING`) driving a 60fps Web Audio `AnalyserNode` orb, Mute (`M`), and instant Interrupt (`Space`). |
| **Speech Pipeline** | `backend/app/services/voice.py` | Single-roundtrip `POST /api/voice/turn` (FFmpeg 16 kHz WAV → `whisper-cli` STT → Agent → macOS `say` WAV TTS) with automatic browser `SpeechRecognition` / `speechSynthesis` fallback. |
| **Conversational Core** | `agent.py`, `local_llm.py` | Context-aware rules + optional **Gemini (`gemini-3.1-flash-lite` → `gemini-3.5-flash-lite` fallback)** for multi-turn English/Hinglish dialogue; LLM-extracted facts require a verbatim quote in `validate_fact_payload()`. |
| **Scoring & CRM** | `scoring.py`, `db.py` | Deterministic `0–100` BANT-style rubric (Requirement 25, Budget ≥₹50,000 25, Timeline ≤30d 25, Decision-maker 25; Hot ≥75, Warm ≥50). LLMs never set scores or write bookings directly. |
| **Grounded RAG & Booking** | `knowledge.py`, `main.py` | TF-IDF lexical retrieval (`knowledge_base/*.md`) + `GET /api/knowledge/search` Gemini grounded synthesis (`✦ Gemini Grounded Answer`); unknown queries escalate instead of guessing. Weekday IST booking enforces overlap checks + idempotency keys. |

---

## 3. Key Differentiators & Engineering Trade-offs

- **AI Authority Boundary:** Business state (scores, verified evidence quotes, calendar availability, handoff flags) stays deterministic in Python/SQLite; Gemini enriches conversational fluency and paraphrasing without hallucinating commitments.
- **Cost-First Local-First Voice:** Zero paid voice/telephony bills required. Local Whisper (`ggml-base.bin`) + native TTS + SQLite run offline on Apple Silicon, with seamless optional cloud intelligence when `GEMINI_API_KEY` is provided in `.env` or via `POST /api/settings/gemini`.
- **Honest Production Path:** Designed for localhost evaluation (no auth or PSTN/WebRTC media server); `docs/scalability.md` defines the target 100,000-user architecture (stateless API tier, LiveKit/Pipecat WebRTC workers, PostgreSQL + `pgvector`, Redis, durable queues).

---

## 4. Verification Summary

- **Automated Suite (`./scripts/run_tests.sh` + GitHub Actions CI):** **19/19 `pytest` tests passing**, `python -m compileall` clean, `node --check backend/app/static/app.js` clean.
- **Live End-to-End Checks:** Verified `/api/health`, `/api/voice/turn` 4-turn speech loop (`whisper-cli` + `Tara` WAV synthesis), live `gemini-3.1-flash-lite` Hinglish qualification + Shopify RAG grounding, and Gemini-powered Hinglish Knowledge Base search (`GET /api/knowledge/search`).
