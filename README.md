# SalesPilot AI — Local-first live voice sales agent

**Version:** 0.2.0 MVP  
**Target:** macOS (Apple Silicon supported), Linux, and Windows with Python 3.10+  
**Paid API requirement:** None. The default MVP uses no hosted LLM, STT, TTS, or database API.

SalesPilot is a runnable live voice-agent sales prototype. It lets customers hold a continuous hands-free voice call (or text chat) in English or Hinglish, turns customer statements into structured evidence-backed CRM facts, calculates a deterministic lead score, retrieves approved product information from local documents, books conflict-checked demo appointments directly in conversation or the calendar panel, and flags human handoffs when needed.

The project stays transparent about its implementation: the conversational core uses deterministic context-aware extraction, conversational booking, and local TF-IDF retrieval by default (with an optional local OpenAI-compatible LLM add-on). Live voice calls run turn-by-turn over continuous Voice Activity Detection (VAD) with Whisper.cpp transcription and macOS native voice synthesis (`say`) feeding a real-time animated Web Audio orb (with automatic browser Web Speech / `speechSynthesis` fallback on other platforms).

## What works in this MVP

- **Live Voice Call Studio**: One-click **Start Live Call** continuous conversation with a 60fps Web Audio reactive voice orb, live call timer, mic Mute/Unmute (`M`), instant Interrupt / Send Now (`Space`), and live captions.
- **Single-Roundtrip Local Speech Pipeline**: `POST /api/voice/turn` combines local Whisper.cpp speech-to-text, agent processing, and macOS `say` WAV synthesis (`POST /api/voice/tts`) with automatic browser Web Speech / `speechSynthesis` fallback.
- **SQLite CRM & Transcript Hydration**: Synthetic demo lead, persisted calls, auto-restored transcripts, clickable Lead Pipeline rows, Evidence Ledger, and appointments with cancellation.
- **Context-Aware Fact Extraction & Evidence Ledger**: Extracts requirement, budget (including Indian formats like `50k`, `50 hazaar`, `1.5 lakhs`, `₹50,000`), timeline (`next month`, `agle hafte`, `asap`), and decision-maker status (including contextual yes/no answers), linking every field to the customer's exact quote.
- **Explainable 0–100 Qualification Score**: Deterministic scoring rubric with criterion-level breakdown and recommended next step.
- **Grounded Local RAG**: Document chunking and TF-IDF lexical retrieval with source citations; escalates to a human when no verified passage supports the question.
- **Conversational & Calendar Appointment Booking**: Book weekday IST demo slots either by voice/chat (*"Can you book a demo for tomorrow at 11 AM?"*) or through the conflict-checked calendar widget.
- **Optional Local LLM Adapter**: Supports an OpenAI-compatible local endpoint (e.g., Ollama or LM Studio) for conversational phrasing while keeping scoring, evidence, and bookings deterministic.

## Quick start on macOS

1. Clone the repository and enter the project folder:

   ```bash
   git clone https://github.com/aadity-dev/Sales-pilot---AI.git
   cd Sales-pilot---AI
   ```

2. Run the launcher:

   ```bash
   ./run.sh
   ```

   The first run creates `.venv` and installs the Python dependencies if needed. No paid account or API key is required.

3. Open [http://127.0.0.1:8008](http://127.0.0.1:8008) (or set `PORT=8000 ./run.sh`).
4. Select **Rahul Sharma** or create a new lead, then click **Start Live Call**!

To stop the server, press `Control+C` in Terminal. A double-clickable `run.command` is also included for macOS.

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8008
```

## Five-minute demo script

1. Select **Rahul Sharma** or create a new lead such as `Priya Sharma / Acme Systems`.
2. **Voice call path**: Click **Start Live Call**, allow microphone access once, and speak naturally across turns (or press `Space` anytime to interrupt the AI and speak immediately, and `M` to mute).
3. **Typed / quick verification path**: Paste or speak this customer statement:

   ```text
   Hi, my name is Priya Sharma. I work at Acme Systems. We need customer support automation. Our budget is ₹50,000, we want to implement it within 30 days, and I am the decision maker.
   ```

4. The application captures requirement, budget, timeline, and decision-maker status in the Evidence Ledger and calculates a deterministic **100/100 (HOT)** score.
5. Ask:

   ```text
   Does your product integrate with Shopify?
   ```

   The sample product FAQ says that native Shopify integration is not confirmed. SalesPilot cites `product_faq.md` instead of inventing a yes/no claim.
6. Ask an unrelated unsupported question, such as `What is your certified satellite launch capability?`. The agent declines to guess and flags a human follow-up.
7. Say `I am frustrated and want to talk to a human sales representative.` to demonstrate negative-sentiment escalation.
8. Ask by voice/text `"Can you book a demo for tomorrow at 11 AM?"` (or pick a weekday slot in **Appointment booking**). Try booking the same slot again with a different idempotency key to see conflict prevention (`409`).

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

### Continuous Live Call & Speech Engines

SalesPilot supports two speech-to-text paths inside **Start Live Call** (selectable via **STT Engine**):

1. **Auto / Local Whisper (Recommended on macOS)**: Keeps a persistent echo-cancelled microphone stream open during the call, calibrates room noise, slices speech turns via browser VAD without clipping the first word, and calls `POST /api/voice/turn` for local Whisper transcription + agent logic + local WAV speech synthesis in one roundtrip.
2. **Browser Live Captions**: Uses the browser's Web Speech API (`SpeechRecognition`) for interim live captions and automatically falls back to Local Whisper if the browser speech service returns a `network` or availability error.

Outside a live call, **One-shot Voice Clip** records a single utterance, transcribes it with Whisper.cpp, and populates the message composer.

### Text-to-speech

- On **macOS**, `POST /api/voice/tts` uses native `/usr/bin/say` voices (**Tara**, **Aman**, **Rishi**, **Lekha**, **Samantha**, **Daniel**) to produce WAV audio streamed through a Web Audio `AnalyserNode` so the Voice Orb animates in real time with the AI's voice.
- On **Linux / Windows** (or when local TTS is unavailable), the dashboard seamlessly falls back to the browser's `speechSynthesis` API. Spoken replies can be toggled off anytime in the Voice Studio.

### Speech-to-text with Whisper.cpp

Local transcription requires `ffmpeg`, a `whisper.cpp` binary (`whisper-cli`), and a compatible GGML model file (model weights are excluded from git via `.gitignore`).

On macOS:

```bash
brew install cmake ffmpeg whisper-cpp
mkdir -p models
curl -L -o models/ggml-base.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
```

Or build from source:

```bash
brew install cmake ffmpeg git
cd ~
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release -j
sh ./models/download-ggml-model.sh base
```

Copy `.env.example` to `.env` and set the paths for your local binary and model:

```text
WHISPER_CPP_BIN=/opt/homebrew/bin/whisper-cli
WHISPER_MODEL_PATH=/absolute/path/to/salespilot_ai/models/ggml-base.bin
```

Restart SalesPilot. The dashboard's text input and browser Web Speech remain usable even if Whisper.cpp is not configured.

## Optional local LLM (no hosted API)

The default app does not contact an LLM service. You may optionally run a local model server exposing an OpenAI-compatible `/v1/chat/completions` endpoint (such as Ollama or LM Studio), then add to `.env`:

```text
SALESPILOT_LOCAL_LLM_URL=http://127.0.0.1:11434/v1/chat/completions
SALESPILOT_LOCAL_LLM_MODEL=qcod:latest
SALESPILOT_LOCAL_LLM_API_KEY=
```

Restart the app. When configured, the local model can phrase retrieved FAQ answers and conversational turns while scoring, evidence quote verification, RAG citations, and appointment bookings remain deterministic in backend code. If the local endpoint is slow or unavailable, SalesPilot falls back immediately to deterministic responses.

## Project structure

```text
salespilot_ai/
├── .github/workflows/
│   └── ci.yml                  # Automated pytest + syntax check workflow
├── backend/app/
│   ├── __main__.py             # Module entry point (python -m backend.app)
│   ├── main.py                 # FastAPI routes and app factory
│   ├── db.py                   # SQLite schema and connections
│   ├── schemas.py              # Pydantic request validation
│   ├── services/
│   │   ├── agent.py            # Context-aware extraction, evidence, booking and workflow
│   │   ├── scoring.py          # Deterministic qualification rubric
│   │   ├── knowledge.py        # Local chunking and TF-IDF-style retrieval
│   │   ├── voice.py            # Whisper.cpp STT & local macOS say TTS helpers
│   │   └── local_llm.py        # Optional local-only model adapter
│   └── static/                 # Browser Voice Studio & dashboard (HTML/CSS/JS)
├── knowledge_base/             # Sample fictional company documents
├── data/                       # Runtime SQLite database folder (.gitkeep tracked)
├── models/                     # Local Whisper model folder (.gitkeep tracked)
├── tests/                      # Automated tests
├── docs/                       # Architecture, security, test report and checklist
├── scripts/                    # Test helper
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
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
- No model weights are bundled in git. Clone stays lightweight and does not redistribute third-party model files.
- The app has no authentication because it is designed for localhost demonstration. Do not expose it to a public network without authentication, TLS, rate limiting, and access controls.
- SQLite is suitable for this MVP, not a 100,000-user production deployment. See `docs/scalability.md` for the proposed target architecture.

## Privacy and safe demo use

Use synthetic customer data. The prototype stores lead details, transcripts, evidence quotes, and appointment details in a local SQLite file under `data/`. The database is not encrypted by the application. Protect your Mac account and disk, do not commit `.env` or customer data, and delete the database after the evaluation if it contains any real information. Recording and processing customer calls in a real deployment requires appropriate consent, retention controls, access restrictions, and legal review.

## Licence and third-party notices

Project code is provided under the MIT License. FastAPI, Uvicorn, pytest, and any optional Whisper.cpp/model software retain their own licences. This repository does not include third-party model weights.
