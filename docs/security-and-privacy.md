# Security and privacy notes

## Current prototype

- Intended for localhost development and evaluator demonstration.
- No authentication or multi-tenant authorization is implemented.
- SQLite records are stored unencrypted in `data/salespilot.db` by default.
- The browser UI uses same-origin local API calls. No third-party analytics or hosted AI API is called by default.
- Optional local model requests go to the operator-configured local endpoint; optional transcription runs the configured local Whisper.cpp executable.
- Use only synthetic lead information and fabricated transcripts during development and evaluation.

## Before real customer use

1. Add authentication, role-based authorization and tenant isolation.
2. Enforce TLS and secure cookie/session settings.
3. Encrypt data at rest and in backups; define key rotation and secret management.
4. Obtain appropriate notice and consent before recording or transcribing calls.
5. Define retention schedules for recordings, transcripts, extracted facts and evidence; implement deletion and export workflows.
6. Minimize stored personal information and redact sensitive data where appropriate.
7. Add audit logs for CRM writes, booking changes, transcript access, evidence corrections and human handoffs.
8. Validate tool arguments server-side and use a strict allowlist of authorized actions.
9. Treat retrieved documents and customer messages as untrusted data; they must not override system instructions or authorize tool actions.
10. Complete applicable privacy, consumer-protection, telemarketing and sector-specific legal review before deployment.

## AI safety boundaries

- Unsupported product claims must not be invented.
- An LLM may phrase a grounded answer, but it cannot directly set scores or create bookings.
- Human transfer is always available when requested.
- Negative sentiment is a signal for review, not a diagnosis of the customer.
- A missing fact remains missing; the agent must ask rather than infer it.
