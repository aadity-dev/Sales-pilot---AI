# Test report — SalesPilot AI MVP 0.2.0

**Execution date:** 26 November 2026  
**Environment:** macOS (Apple M2), Python 3.15.2, FastAPI 0.165.0, Uvicorn 0.54.0, pytest 9.2.0, Node.js (checked `app.js`), Whisper.cpp (`ggml-base.bin`), FFmpeg, macOS `say`

## Automated results

- `python -m pytest tests/ -v` — **18 passed**.
- `node --check backend/app/static/app.js` — **passed** (JavaScript syntax check).
- `python -m compileall -q backend` — **passed** (Python compilation check).
- Live Uvicorn + voice turn end-to-end verification (temporary SQLite DB on port `8118` and `8117`):
  - `GET /`, `/static/styles.css`, `/static/app.js`, and `/api/health` returned HTTP 200.
  - `GET /api/knowledge/search?q=Is+my+data+secure?` returned `product_faq.md` (`score=3.8093`).
  - `POST /api/voice/turn` transcribed synthesized WAV audio via `whisper-cli` + `ggml-base.bin`, executed deterministic scoring/RAG/booking across 4 turns, and returned `Tara` WAV audio.

The pytest suite covers:

- Application health and seeded synthetic demo lead.
- Lead creation and the qualification workflow.
- Explicit fact extraction, contextual decision-maker replies, Hinglish/Indian budget parsing (`50 hazaar`, `1.5 lakhs`), and Evidence Ledger records.
- Gemini API multi-turn conversational handling (`thinkingBudget: 0`), `/api/settings/gemini` configuration, and rejection of unquoted LLM facts.
- Deterministic scoring and lead status.
- Sentiment classification and human escalation.
- RAG citation for a documented answer and handoff for an unsupported question.
- Conversational demo booking inside chat/voice (`POST /api/agent/chat`), idempotency, slot conflict (`409`), availability refresh, and cancellation.
- Knowledge document listing (`GET /api/knowledge/documents`) and voice capabilities (`GET /api/voice/voices`).
- Speech text cleanup (`format_for_speech` removing markdown and formatting rupees).
- Dashboard and OpenAPI documentation routes.
- Expected `501` response on `/api/voice/transcribe` and `/api/voice/turn` when Whisper.cpp is not configured.

## Not verified in this run

- Automated Playwright/headless browser microphone clicking and Web Audio canvas rendering were not run in CI; JS syntax passed `node --check` and live server routes were verified via `httpx`.
- The optional local LLM adapter (`Ollama` / `LM Studio`) was not enabled in default `.env`; deterministic local workflow was exercised.
- No production load test or 100,000-user capacity test was performed. `docs/scalability.md` is an architecture proposal, not a benchmark.

## Re-running

From the project root:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
node --check backend/app/static/app.js
python3 -m compileall -q backend
```
