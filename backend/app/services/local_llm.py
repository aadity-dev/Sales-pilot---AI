"""Optional OpenAI-compatible local model adapter (no hosted API required).

The adapter is disabled unless SALESPILOT_LOCAL_LLM_URL is explicitly set to a
model server running on the operator's machine. Model-extracted facts are accepted
only when the model includes a verbatim evidence quote from the user's message.
The adapter never calculates lead scores or authorizes CRM/calendar actions.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

ALLOWED_FIELDS = {"name", "company", "requirement", "budget_amount", "timeline_days", "decision_maker"}


def _local_completion(messages: list[dict[str, str]], temperature: float = 0.0, timeout: float = 8.0) -> str | None:
    endpoint = os.getenv("SALESPILOT_LOCAL_LLM_URL", "").strip()
    if not endpoint:
        return None
    model = os.getenv("SALESPILOT_LOCAL_LLM_MODEL", "local-model").strip() or "local-model"
    api_key = os.getenv("SALESPILOT_LOCAL_LLM_API_KEY", "").strip()
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        return content.strip() if isinstance(content, str) and content.strip() else None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None


def is_local_llm_reachable(timeout: float = 0.4) -> bool:
    endpoint = os.getenv("SALESPILOT_LOCAL_LLM_URL", "").strip()
    if not endpoint:
        return False
    base = endpoint.split("/v1/")[0].rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/v1/models", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def validate_fact_payload(message: str, payload: Any) -> dict[str, dict[str, Any]]:
    """Accept only allowlisted fields accompanied by an exact quote in the message."""
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
        return {}
    accepted: dict[str, dict[str, Any]] = {}
    for item in payload["facts"]:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        value = item.get("value")
        quote = item.get("quote")
        if field not in ALLOWED_FIELDS or not isinstance(quote, str) or not quote or quote not in message:
            continue
        if field in {"name", "company", "requirement"}:
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()[:200]
        elif field in {"budget_amount", "timeline_days"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                continue
            value = int(value)
            if field == "timeline_days" and value > 3650:
                continue
            if field == "budget_amount" and value > 100_000_000_000:
                continue
        elif field == "decision_maker":
            if not isinstance(value, bool):
                continue
        accepted[field] = {"value": value, "quote": quote}
    return accepted


def extract_verified_facts(message: str) -> dict[str, dict[str, Any]]:
    """Ask an optional local model for structured facts and validate each quote."""
    content = _local_completion(
        [
            {
                "role": "system",
                "content": (
                    "Extract only facts the customer explicitly stated. Return JSON only in this schema: "
                    '{"facts":[{"field":"requirement","value":"...","quote":"exact verbatim substring"}]}. '
                    "Allowed fields: name, company, requirement, budget_amount (integer INR), timeline_days (integer), "
                    "decision_maker (boolean). Every item MUST include quote copied exactly from the customer message. "
                    "Do not infer missing values. Use an empty facts array when no facts are explicit."
                ),
            },
            {"role": "user", "content": message},
        ],
        temperature=0.0,
    )
    if not content:
        return {}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return validate_fact_payload(message, parsed)


def generate_grounded_answer(question: str, passages: list[dict[str, Any]]) -> str | None:
    if not passages:
        return None
    context = "\n\n".join(
        f"SOURCE: {item.get('source')}\nPASSAGE: {item.get('content')}" for item in passages[:3]
    )
    content = _local_completion(
        [
            {
                "role": "system",
                "content": (
                    "You are SalesPilot, a careful sales assistant. Answer only using the supplied source passages. "
                    "Do not add facts, prices, integrations, guarantees, or policies not present in the passages. "
                    "If the passages do not answer the question, say you cannot verify it and suggest a human follow-up. "
                    "Keep the answer brief and conversational. Return JSON with one string field named answer."
                ),
            },
            {"role": "user", "content": f"Customer question: {question}\n\nApproved knowledge passages:\n{context}"},
        ],
        temperature=0.1,
    )
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    answer = parsed.get("answer") if isinstance(parsed, dict) else None
    return answer.strip()[:2000] if isinstance(answer, str) and answer.strip() else None


def generate_conversational_reply(
    customer_message: str,
    lead: dict[str, Any],
    next_question: str | None,
    captured_summary: str,
    language: str = "en-IN",
) -> str | None:
    """Optional local model phrasing for natural voice turns; deterministic workflow stays authoritative."""
    if not os.getenv("SALESPILOT_LOCAL_LLM_URL", "").strip():
        return None
    lang_note = "Reply naturally in warm Hinglish or simple Hindi." if language.startswith("hi") else "Reply in warm, natural, spoken English (1 to 2 short sentences)."
    content = _local_completion(
        [
            {
                "role": "system",
                "content": (
                    "You are SalesPilot, a helpful live voice sales assistant. Keep replies concise (under 35 words) "
                    "so they sound natural when spoken aloud. Never invent product prices, integrations, or commitments. "
                    f"{lang_note} Return JSON: {{\"answer\": \"...\"}}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Customer just said: {customer_message}\n"
                    f"Lead name: {lead.get('name') or 'Customer'}\n"
                    f"Facts captured this turn: {captured_summary or 'None'}\n"
                    f"Next question to ask naturally (if any): {next_question or 'Ask if they would like to book a 30-minute product demo.'}"
                ),
            },
        ],
        temperature=0.25,
        timeout=6.0,
    )
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    answer = parsed.get("answer") if isinstance(parsed, dict) else None
    return answer.strip()[:500] if isinstance(answer, str) and answer.strip() else None
