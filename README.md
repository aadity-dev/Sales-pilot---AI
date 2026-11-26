# SalesPilot AI — Local-first live voice sales agent

**Version:** 0.2.0 MVP  
**Target:** macOS (Apple Silicon supported), Linux, and Windows with Python 3.10+  
**Paid API requirement:** None. The default MVP uses no hosted LLM, STT, TTS, or database API.

SalesPilot is a runnable live voice-agent sales prototype. It lets customers hold a continuous hands-free voice call (or text chat) in English or Hinglish, turns customer statements into structured evidence-backed CRM facts, calculates a deterministic lead score, retrieves approved product information from local documents, books conflict-checked demo appointments directly in conversation or the calendar panel, and flags human handoffs when needed.

The project stays transparent about its implementation: the conversational core uses deterministic context-aware extraction, conversational booking, and local TF-IDF retrieval by default (with an optional local OpenAI-compatible LLM add-on). Live voice calls run turn-by-turn over continuous Voice Activity Detection (VAD) with Whisper.cpp transcription and macOS native voice synthesis (`say`) feeding a real-time animated Web Audio orb (with automatic browser Web Speech / `speechSynthesis` fallback on other platforms).

## What works in this MVP

- **Live Voice Call Studio**: One-click continuous voice call with an interactive Web Audio voice orb visualizer, call timer, mic mute/unmute, Spacebar / button barge-in interruption, and live captions.
- **Fast Local Speech Pipeline**: Local Whisper.cpp speech-to-text (`/api/voice/turn` single-roundtrip STT + agent + TTS) and macOS native `say` WAV synthesis (`/api/voice/tts`) with automatic browser fallback.
- **SQLite CRM & Transcript Hydration**: Synthetic demo lead, persisted calls, auto-restored transcripts, clickable Lead Pipeline rows, evidence ledger, and appointments with cancellation.
- **Context-Aware Fact Extraction & Evidence Ledger**: Extracts requirement, budget (including Indian formats like `50k`, `50 hazaar`, `1.5 lakhs`, `₹50,000`), timeline, and decision-maker status (including contextual yes/no answers), linking every field to the customer's exact quote.
- **Explainable 0–100 Qualification Score**: Deterministic scoring rubric with criterion-level breakdown and recommended next step.
- **Grounded Local RAG**: Document chunking and TF-IDF lexical retrieval with source citations; escalates to a human when no verified passage supports the question.
- **Conversational & Calendar Appointment Booking**: Book weekday IST demo slots either by voice/chat (*"Book a demo tomorrow at 11 AM"*) or through the conflict-checked calendar widget.
- **Optional Local LLM Adapter**: Supports an OpenAI-compatible local endpoint (e.g., Ollama / LM Studio) for phrasing answers while keeping scoring, evidence, and bookings deterministic.

## Quick start on macOS

1. Open Terminal and move into the project folder:

   ```bash
   cd salespilot_ai
   ```

2. Run the launcher:

   ```bash
   ./run.sh
   ```

   The first run creates `.venv` and installs the Python dependencies if needed. No paid account or API key is required.

3. Open [http://127.0.0.1:8008](http://127.0.0.1:8008) (or set `PORT=8000 ./run.sh`).
4. Select **Rahul Sharma** or create a new lead, then click **Start Live Call**!

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

## Five-minute demo script

1. Select **Rahul Sharma** or create a lead such as `Priya Sharma / Acme Systems`.
2. Click the plus button beside the customer selector to start a conversation.
3. Paste or type this customer statement:

   ```text
   Hi, my name is Priya Sharma. I work at Acme Systems. We need customer support automation. Our budget is ₹50,000, we want to implement it within 30 days, and I am the decision maker.
   ```

4. The application should capture the requirement, budget, timeline, and decision-maker status. The deterministic scoring rubric should show 100/100 for this example.
5. Ask:

   ```text
   Does your product integrate with Shopify?
   ```

   The sample product FAQ says that Shopify integration is not confirmed. SalesPilot should cite the sample FAQ passage instead of inventing a yes/no claim.

6. Ask an unrelated unsupported question, such as `Do you have a certified satellite launch capability?`. The agent should decline to guess and recommend a human follow-up.
7. Say `I am frustrated and want to talk to a human sales representative.` to demonstrate negative-sentiment escalation.
8. Choose a future weekday, select an available demo slot, and confirm the appointment. Try booking the same slot again with a different idempotency key to see the conflict response.

The knowledge-base files are fictional demonstration content. Do not present their prices or capabilities as real products.

## Run automated tests

Install test dependencies and run the suite:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

Or run:

```bash
./scripts/run_tests.sh
```

Tests use a temporary SQLite database and synthetic product documentation. They do not alter your real project database.

## Voice setup (optional, local)

### Low-cost real-time voice path

For the interview demo, press **Live voice**, speak, and let the final transcript auto-send. The browser provides interim captions while you speak; SalesPilot sends only the final utterance to the backend, then speaks the agent reply with browser TTS. This has **no per-minute STT or TTS API bill to SalesPilot**.

This is a cost-first prototype path, not a privacy guarantee: browser speech recognition may be processed by the browser vendor or its configured service. Use Chrome or Edge for the most reliable support and obtain consent before capturing customer speech. If it is unavailable, use the typed flow or the local Whisper.cpp fallback below.

### Text-to-speech

The dashboard uses the browser's built-in `speechSynthesis` API. It does not require a paid TTS provider. Available voices depend on the browser and voices installed on the operating system. Spoken replies can be switched off in the dashboard.

### Speech-to-text with Whisper.cpp

The **Local record** button records audio in the browser. It converts the browser's WebM recording to a 16 kHz mono WAV with FFmpeg before sending it to Whisper.cpp. Actual transcription requires a local Whisper.cpp binary and a compatible model file; neither a binary nor model weights are bundled here. It is slower than Live voice but keeps transcription on your own machine once configured.

On macOS, one possible setup is:

```bash
brew install cmake ffmpeg git
cd ~
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release -j
sh ./models/download-ggml-model.sh small
```

Copy `.env.example` to `.env` and set the paths for your local build and model:

```text
WHISPER_CPP_BIN=/absolute/path/to/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL_PATH=/absolute/path/to/whisper.cpp/models/ggml-small.bin
```

Restart SalesPilot. The API expects a Whisper.cpp CLI build capable of reading the audio format produced by your browser. If your build cannot read WebM audio, convert it to WAV with FFmpeg or build Whisper.cpp with FFmpeg support. The dashboard's text input remains fully usable without Whisper.

A small multilingual Whisper model is a reasonable starting point on an 8 GB Apple Silicon Mac, but actual latency and language accuracy must be benchmarked on your machine. This prototype does not claim production-grade Hindi/Hinglish telephony recognition.

## Optional local LLM (no hosted API)

The default app does not contact an LLM service. You may optionally run a local model server that exposes an OpenAI-compatible `/v1/chat/completions` endpoint. For example, configure LM Studio to serve a compatible small instruct model locally, then add to `.env`:

```text
SALESPILOT_LOCAL_LLM_URL=http://127.0.0.1:1234/v1/chat/completions
SALESPILOT_LOCAL_LLM_MODEL=your-loaded-local-model-id
SALESPILOT_LOCAL_LLM_API_KEY=
```

Restart the app. When SalesPilot retrieves relevant product passages, it can ask the local model to phrase an answer using only those passages. If the local endpoint is unavailable or returns an invalid response, the deterministic retrieved passage answer is used instead. The model does not calculate scores, update the CRM, or book appointments.

This adapter does not download a model or start a model server for you. Model files may be several gigabytes and are not included in the ZIP. With an 8 GB Mac, use a small quantized model and close memory-heavy applications.

## Project structure

```text
salespilot_ai/
├── backend/app/
│   ├── main.py                 # FastAPI routes and app factory
│   ├── db.py                   # SQLite schema and connections
│   ├── schemas.py              # Request validation
│   ├── services/
│   │   ├── agent.py            # Context-aware extraction, evidence, booking and workflow
│   │   ├── scoring.py          # Deterministic qualification rubric
│   │   ├── knowledge.py        # Local chunking and TF-IDF-style retrieval
│   │   ├── voice.py            # Whisper.cpp STT & local macOS say TTS helpers
│   │   └── local_llm.py        # Optional local-only model adapter
│   └── static/                 # Browser Voice Studio & dashboard (HTML/CSS/JS)
├── knowledge_base/             # Sample fictional company documents
├── data/                       # SQLite database created at runtime
├── tests/                      # Automated tests
├── docs/                       # Architecture, security and evaluation notes
├── scripts/                    # Test helper
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── run.sh
└── run.command
```

## API overview

FastAPI interactive docs are available at `http://127.0.0.1:8008/docs` while the server is running via `./run.sh`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Local service and configuration health |
| GET | `/api/dashboard/stats` | Lead, booking and handoff counts |
| GET/POST | `/api/leads` | List and create leads |
| GET | `/api/leads/{lead_id}` | Lead, evidence, latest transcript, call and booking details |
| POST | `/api/calls` | Start a call/conversation session |
| POST | `/api/agent/chat` | Send a customer message and receive agent output |
| GET | `/api/calls/{call_id}` | Retrieve transcript messages |
| GET | `/api/knowledge/documents` | List indexed knowledge documents and chunk counts |
| GET | `/api/knowledge/search?q=...` | Search local knowledge documents |
| POST | `/api/knowledge/reload` | Re-index local Markdown/text documents |
| GET | `/api/appointments/availability?for_date=YYYY-MM-DD` | List available demo slots |
| GET/POST | `/api/appointments` | List and book appointments |
| POST | `/api/appointments/{id}/cancel` | Cancel an appointment |
| GET | `/api/voice/voices` | List local TTS voices and voice capabilities |
| POST | `/api/voice/tts` | Synthesize local WAV speech (macOS `say`) |
| POST | `/api/voice/transcribe` | Local Whisper.cpp audio transcription |
| POST | `/api/voice/turn` | Single-roundtrip Whisper STT + agent reply + TTS WAV |
| GET | `/api/settings` | Runtime capability disclosure |

## Lead scoring rubric

The score is calculated in backend code; the LLM cannot directly choose it.

| Criterion | Maximum | Rule |
|---|---:|---|
| Clear requirement | 25 | 25 when explicitly captured |
| Budget | 25 | 25 at ₹50,000 or more; 15 below that; 0 if missing |
| Purchase timeline | 25 | 25 within 30 days; 15 within 90 days; 5 later; 0 if missing |
| Decision-maker | 25 | 25 when explicitly confirmed; 0 when missing or not the decision-maker |

Lead status: Hot ≥75, Warm ≥50, otherwise Cold. These are demo qualification rules, not a validated sales-science model. Adjust them to a real business's ICP and conversion data before deployment.

## Known limitations — read before evaluation

- This is a **functional MVP**, not a production PSTN voice-calling platform.
- The default agent brain uses deterministic phrase/regex extraction, conversational context tracking, and a rules-based decision flow. It is not a fully autonomous general-purpose LLM agent unless you configure a local model endpoint.
- Retrieval is lexical TF-IDF-style scoring, not a vector embedding database. It works for the included sample documents and is a replaceable MVP retrieval layer.
- Local WAV TTS uses macOS `say` on Darwin and falls back automatically to browser `speechSynthesis` on other platforms. Local speech recognition requires Whisper.cpp + FFmpeg and a Whisper model file.
- Real PSTN/SIP telephony, outbound dialing, live full-duplex WebRTC media servers, and production CRM/calendar vendor integrations are not implemented.
- The appointment calendar is a local demo scheduler. It is not connected to Google Calendar or another external calendar.
- The UI provides continuous browser VAD turn-taking with Spacebar / optional headphone barge-in over HTTP turns (`/api/voice/turn`), rather than sub-200ms full-duplex WebRTC streaming.
- No model weights are bundled. The ZIP remains small and does not redistribute third-party model files.
- The app has no authentication because it is designed for localhost demonstration. Do not expose it to a public network without authentication, TLS, rate limiting, and access controls.
- SQLite is suitable for this MVP, not a 100,000-user production deployment. See `docs/scalability.md` for the proposed target architecture.

## Privacy and safe demo use

Use synthetic customer data. The prototype stores lead details, transcripts, evidence quotes, and appointment details in a local SQLite file under `data/`. The database is not encrypted by the application. Protect your Mac account and disk, do not commit `.env` or customer data, and delete the database after the evaluation if it contains any real information. Recording and processing customer calls in a real deployment requires appropriate consent, retention controls, access restrictions, and legal review.

## Licence and third-party notices

Project code is provided under the MIT License. FastAPI, Uvicorn, pytest, and any optional Whisper.cpp/model software retain their own licences. This repository does not include third-party model weights.
