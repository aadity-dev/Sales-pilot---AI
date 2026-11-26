# Evaluation checklist

## Live demonstration

- [ ] Open the dashboard from localhost.
- [ ] Create a synthetic lead.
- [ ] Start a call session and submit customer messages.
- [ ] Confirm requirement, budget, timeline and decision-maker facts are extracted.
- [ ] Click through the evidence ledger and verify quotes.
- [ ] Explain the deterministic score and status threshold.
- [ ] Ask a product question and show its source citation.
- [ ] Ask an unsupported question and show refusal / human follow-up.
- [ ] Trigger a human handoff through a direct customer request or negative wording.
- [ ] Book a future demo slot and demonstrate conflict prevention.
- [ ] Show test results and the architecture diagram.

## Suggested live coding changes

1. Change the hot-lead threshold in `backend/app/services/scoring.py`.
2. Add a new sample product FAQ to `knowledge_base/` and re-index it.
3. Add a new deterministic extraction rule to `extract_facts` and add a unit test.
4. Modify the appointment slot schedule in `backend/app/main.py` and test the conflict behaviour.

## Claims to avoid

- Do not say the MVP supports 100,000 concurrent calls; only the target architecture is documented.
- Do not say speech recognition works out of the box; Whisper.cpp and model files must be installed separately.
- Do not say the default app is powered by a generative LLM; deterministic local workflow is the default.
- Do not call the local SQLite scheduler Google Calendar integration.
- Do not claim the fictional sample product's pricing and integrations are real.
