# Test report — SalesPilot AI MVP 0.1.0

**Execution date:** 25 November 2026  
**Environment:** Python 3.13.5, FastAPI 0.128.2, Uvicorn 0.48.0, pytest 9.0.2, Node.js 22.16.0

## Automated results

- `python -m pytest -q` — **13 passed**.
- `node --check backend/app/static/app.js` — **passed** (JavaScript syntax check).
- `python -m compileall -q backend` — **passed** (Python compilation check).
- Live Uvicorn smoke test — **passed**: `/api/health` returned HTTP 200 and `/` returned HTTP 200.

The pytest suite covers:

- Application health and seeded synthetic demo lead.
- Lead creation and the qualification workflow.
- Explicit fact extraction and evidence-ledger records.
- Deterministic scoring and lead status.
- Sentiment/human escalation.
- RAG citation for a documented answer and handoff for an unsupported question.
- Appointment booking, idempotency, slot conflict, availability refresh and cancellation.
- Dashboard and OpenAPI documentation routes.
- The expected `501` response when optional Whisper.cpp is not configured.

## Not verified in this environment

- A full interactive browser run was attempted with Playwright and the system Chromium executable, but navigation to the local server was blocked by the environment with `ERR_BLOCKED_BY_ADMINISTRATOR`. The static dashboard route itself returned HTTP 200 and its JavaScript passed `node --check`; visual browser interaction was therefore not certified here.
- Whisper.cpp speech recognition was not exercised because the binary and model weights are not included or configured.
- The optional local LLM adapter was not exercised because no local model server was configured.
- No production load test or 100,000-user capacity test was performed. The scalability document is an architecture proposal, not a benchmark.

## Re-running

From the project root:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
node --check backend/app/static/app.js
python3 -m compileall -q backend
```
