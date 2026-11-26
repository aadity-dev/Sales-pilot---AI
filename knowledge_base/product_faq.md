# SalesPilot AI — Product Information

## Product overview
SalesPilot AI is an AI-powered sales-assistant application for qualifying inbound leads, answering approved product questions, capturing evidence from conversations, scheduling demonstrations, and handing complex or sensitive conversations to a human sales representative.

## What SalesPilot AI does today
SalesPilot AI provides a working sales workflow: a customer can speak or type a requirement, the agent records the conversation, captures budget, timeline, and decision-maker signals, calculates an explainable lead score, retrieves approved knowledge-base answers, and offers an available demonstration slot. Each captured lead fact is linked to the exact customer statement that supported it.

## Voice and languages
SalesPilot AI supports browser text-to-speech and local Whisper speech-to-text. The installed multilingual model can transcribe English and Hindi. Live browser speech recognition is used when the browser service is available; if it is unavailable, SalesPilot automatically switches to local recording and transcription. Qualification scoring is currently optimized for English; multilingual extraction is an active product extension.

## Integrations
The current application includes local CRM records and a conflict-checked appointment calendar. Production adapters for external CRMs, calendars, telephony, and messaging platforms are designed as integration points and are enabled only after the customer selects and authorizes a provider. Native Shopify integration is not confirmed in this MVP; a product specialist must verify custom e-commerce connector requirements.

## Security and privacy
SalesPilot AI stores CRM records, messages, evidence, and appointments in its local database, keeping customer data secure on your machine by default. Local speech transcription and native voice synthesis can run without sending audio to a paid AI API. Production deployments require customer consent, authentication, encryption, role-based access, retention controls, and audit logging.

## Support and escalation
SalesPilot AI escalates a conversation when a customer requests a human representative, expresses negative sentiment, or asks a question not supported by approved knowledge. It does not invent product commitments.
