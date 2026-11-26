# Test report — SalesPilot AI MVP 0.2.0

**Execution date:** 26 November 2026  
**Environment:** macOS (Apple M2), Python 3.15.2, FastAPI 0.165.0, Uvicorn 0.54.0, pytest 9.2.0, Node.js (checked `app.js`), Whisper.cpp (`ggml-base.bin`), FFmpeg, macOS `say`, Gemini (`gemini-3.1-flash-lite`)

## Automated results

- `./scripts/run_tests.sh` (`python -m pytest -v`, `python -m compileall -q backend`, `node --check backend/app/static/app.js`) — **19 passed**.
- Live Uvicorn verification (temporary SQLite DBs on ports `8117`, `8118`, `8119`, `8120` and active server on `8008`):
  - `GET /`, `/static/styles.css`, `/static/app.js`, and `/api/health` returned HTTP 200 (`gemini_configured: true`, `gemini_model: "gemini-3.1-flash-lite"`, `speech_to_text_configured: true`, `text_to_speech_configured: true`).
  - `GET /api/knowledge/search?q=Is+my+data+secure?` returned `product_faq.md` (`score=3.8093`).
  - `GET /api/knowledge/search?q=Demo+kitne+minute+ka+hota+hai?` returned `ai_mode: "gemini_assisted"`, `ai_supported: True`, `ai_sources: ["pricing.md"]`.
  - `POST /api/agent/chat` live multi-turn Hinglish + Shopify RAG verification returned `response_mode: "gemini_assisted"`, deterministic `score: 50`, extracted `requirement` + `budget_amount: 50000`, and `product_faq.md` citations.
  - `POST /api/voice/turn` transcribed synthesized WAV audio via `whisper-cli` + `ggml-base.bin`, executed deterministic scoring/RAG/booking across 4 turns, and returned `Tara` WAV audio.

The pytest suite covers:

- Application health and seeded synthetic demo lead.
- Lead creation and the qualification workflow.
- Explicit fact extraction, contextual decision-maker replies, Hinglish/Indian budget parsing (`50 hazaar`, `1.5 lakhs`), and Evidence Ledger records.
- Gemini API multi-turn conversational handling (`gemini-3.1-flash-lite` with `thinkingLevel: minimal`), `/api/settings/gemini` configuration, rejection of unquoted LLM facts, and Gemini-powered Knowledge Base search (`GET /api/knowledge/search`).
- Deterministic scoring and lead status.
- Sentiment classification and human escalation.
- RAG citation for a documented answer and handoff for an unsupported question.
- Conversational demo booking inside chat/voice (`POST /api/agent/chat`), idempotency, slot conflict (`409`), availability refresh, and cancellation.
- Knowledge document listing (`GET /api/knowledge/documents`) and voice capabilities (`GET /api/voice/voices`).
- Speech text cleanup (`format_for_speech` removing markdown and formatting rupees).
- Dashboard and OpenAPI documentation routes.
- Expected `501` response on `/api/voice/transcribe` and `/api/voice/turn` when Whisper.cpp is not configured.

## Not verified in this run

- Automated Playwright/headless browser UI clicks (e.g., mic button and Create Lead form submission in headless Chromium) were not run; JS syntax passed `node --check`, DOM IDs + `formEl.reset()` passed audit, and live static assets + API endpoints were verified via `curl`/`httpx`.
- The optional local LLM adapter (`Ollama` / `LM Studio`) was not enabled in `.env`; live Gemini `gemini-3.1-flash-lite` and offline deterministic workflows were exercised.
- No production load test or 100,000-user capacity test was performed. `docs/scalability.md` is an architecture proposal, not a benchmark.

## Re-running

From the project root:

```bash
./scripts/run_tests.sh
```
