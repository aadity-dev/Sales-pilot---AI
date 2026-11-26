# Evaluation checklist

## Live demonstration

- [ ] Open the dashboard from localhost (`http://127.0.0.1:8008` via `./run.sh`).
- [ ] Verify the **✦ Gemini** pill in the topbar (or connect an API key via the modal).
- [ ] Create a synthetic lead (confirm form resets cleanly) or select **Rahul Sharma** from the Lead Pipeline table.
- [ ] Click **Start Live Call** (watch the Voice Orb transition across `LISTENING` -> `THINKING` -> `SPEAKING` -> `LISTENING`) or submit typed customer messages in English or Hinglish.
- [ ] Confirm requirement, budget (`₹50,000`, `50k`, `50 hazaar`, `half a lakh`), timeline, and decision-maker facts (including contextual `"Yes, I am"`) are extracted.
- [ ] Click through the Evidence Ledger and verify verbatim transcript quotes.
- [ ] Explain the deterministic score (`0–100`) and status thresholds (`Hot >= 75`, `Warm >= 50`, `Cold < 50`).
- [ ] Test Knowledge Base search (`GET /api/knowledge/search`) with `"Demo kitne minute ka hota hai?"` or `"Does your product integrate with Shopify?"` and show the **✦ Gemini Grounded Answer** card + source citations.
- [ ] Ask an unsupported question (`What is your certified satellite launch capability?`) and show refusal + human follow-up flag.
- [ ] Trigger a human handoff through a direct customer request or negative sentiment.
- [ ] Book a future demo slot via voice/chat (`Can you book a demo for tomorrow at 11 AM?`) or the calendar widget, and demonstrate conflict prevention and cancellation.
- [ ] Show test results (`./scripts/run_tests.sh`) and the architecture diagram in `docs/architecture.md`.

## Suggested live coding changes

1. Change the hot-lead threshold in `backend/app/services/scoring.py`.
2. Add a new sample product FAQ to `knowledge_base/` and click **Re-index knowledge documents** in the UI.
3. Add a new deterministic extraction rule to `extract_facts` in `backend/app/services/agent.py` and add a unit test in `tests/test_agent_logic.py`.
4. Modify `DEMO_HOURS` in `backend/app/services/agent.py` and `backend/app/main.py` and test the conflict behaviour.

## Claims to avoid

- Do not say the MVP supports 100,000 concurrent calls; only the target architecture in `docs/scalability.md` is documented.
- Do not say Whisper.cpp weights are bundled in the git repo; when cloning fresh, `whisper.cpp`, `ffmpeg`, and a GGML model must be installed separately (see `README.md`).
- Do not say the offline default requires a paid/hosted LLM; deterministic local workflow runs with zero API keys, and Gemini (`gemini-3.1-flash-lite`) or a local OpenAI-compatible LLM is an optional enhancement.
- Do not call the local SQLite scheduler Google Calendar integration.
- Do not claim the fictional sample product's pricing and integrations are real.
