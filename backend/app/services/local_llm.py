"""Optional LLM adapters: Google Gemini API and OpenAI-compatible local endpoints.

No hosted API key is required for the default MVP workflow. When GEMINI_API_KEY
(or GOOGLE_API_KEY) or SALESPILOT_LOCAL_LLM_URL is configured, the adapter
enables natural multi-turn conversation and grounded RAG phrasing while keeping
lead scoring, verbatim evidence verification, and calendar bookings deterministic.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("salespilot.llm")

ALLOWED_FIELDS = {"name", "company", "requirement", "budget_amount", "timeline_days", "decision_maker"}
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


def _thinking_config_for(model: str) -> dict[str, Any] | None:
    m = model.lower()
    if "2.5" in m:
        return {"thinkingBudget": 0}
    if "3.8" in m or "flash-latest" in m:
        return {"thinkingLevel": "low"}
    if "3." in m or "3-" in m:
        return {"thinkingLevel": "minimal"}
    return None


def get_gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def is_gemini_configured() -> bool:
    return bool(get_gemini_api_key())


def is_llm_configured() -> bool:
    return is_gemini_configured() or bool(os.getenv("SALESPILOT_LOCAL_LLM_URL", "").strip())


def active_llm_provider() -> str | None:
    if is_gemini_configured():
        return f"gemini:{get_gemini_model()}"
    if os.getenv("SALESPILOT_LOCAL_LLM_URL", "").strip():
        return f"local:{os.getenv('SALESPILOT_LOCAL_LLM_MODEL', 'local-model').strip() or 'local-model'}"
    return None


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def verify_gemini_key(api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> tuple[bool, str]:
    """Validate a Gemini API key and model generation availability."""
    clean_key = api_key.strip()
    clean_model = (model or DEFAULT_GEMINI_MODEL).strip()
    if not clean_key:
        return False, "API key cannot be empty."
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(clean_model)}:generateContent?key={urllib.parse.quote(clean_key)}"
    )
    gen_config: dict[str, Any] = {"maxOutputTokens": 12, "temperature": 0.0}
    tc = _thinking_config_for(clean_model)
    if tc:
        gen_config["thinkingConfig"] = tc
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with OK"}]}],
        "generationConfig": gen_config,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            json.loads(resp.read().decode("utf-8"))
        return True, f"Connected to {clean_model}"
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            err = ""
        return False, err or f"Gemini API rejected the key (HTTP {exc.code})."
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, f"Could not reach Gemini API: {exc}"


def _gemini_json_completion(
    system_prompt: str,
    turns: list[dict[str, str]],
    temperature: float = 0.25,
    timeout: float = 15.0,
) -> str | None:
    api_key = get_gemini_api_key()
    if not api_key:
        return None
    model = get_gemini_model()

    contents = []
    for item in turns:
        role = "model" if item.get("role") in {"assistant", "agent", "model"} else "user"
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        # Merge consecutive turns with the same role to satisfy Gemini turn alternation.
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n" + text
        else:
            contents.append({"role": role, "parts": [{"text": text}]})

    if not contents or contents[-1]["role"] != "user":
        return None

    models_to_try = [model]
    if model == DEFAULT_GEMINI_MODEL:
        models_to_try.append("gemini-3.5-flash-lite")

    for candidate_model in models_to_try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(candidate_model)}:generateContent?key={urllib.parse.quote(api_key)}"
        )
        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "maxOutputTokens": 450,
        }
        tc = _thinking_config_for(candidate_model)
        if tc:
            gen_config["thinkingConfig"] = tc

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": gen_config,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(max(timeout, 12.0), 15.0)) as response:
                result = json.loads(response.read().decode("utf-8"))
            candidates = result.get("candidates") or []
            parts = candidates[0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if text:
                return _strip_json_fences(text)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            logger.warning("Gemini request failed for %s: %s", candidate_model, exc)
            continue
    return None


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
        return _strip_json_fences(content) if isinstance(content, str) and content.strip() else None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None


def _complete_json(
    system_prompt: str,
    user_prompt: str,
    history: list[dict[str, str]] | None = None,
    temperature: float = 0.2,
    timeout: float = 10.0,
) -> str | None:
    if is_gemini_configured():
        turns = list(history or [])
        turns.append({"role": "user", "text": user_prompt})
        reply = _gemini_json_completion(system_prompt, turns, temperature=temperature, timeout=timeout)
        if reply:
            return reply

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in (history or []):
        role = "assistant" if item.get("role") in {"assistant", "agent", "model"} else "user"
        text = str(item.get("text") or item.get("content") or "").strip()
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_prompt})
    return _local_completion(messages, temperature=temperature, timeout=timeout)


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
    """Ask the configured LLM for structured facts and validate each verbatim quote."""
    if not is_llm_configured():
        return {}
    content = _complete_json(
        system_prompt=(
            "Extract only facts the customer explicitly stated. Return JSON only in this schema: "
            '{"facts":[{"field":"requirement","value":"...","quote":"exact verbatim substring"}]}. '
            "Allowed fields: name, company, requirement, budget_amount (integer INR), timeline_days (integer), "
            "decision_maker (boolean). Every item MUST include quote copied verbatim from the customer message. "
            "Do not infer missing values. Use an empty facts array when no facts are explicit."
        ),
        user_prompt=message,
        temperature=0.0,
    )
    if not content:
        return {}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return validate_fact_payload(message, parsed)


def generate_grounded_answer(
    question: str,
    passages: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
    language: str = "en-IN",
) -> str | None:
    if not passages or not is_llm_configured():
        return None
    context = "\n\n".join(
        f"SOURCE: {item.get('source')}\nPASSAGE: {item.get('content')}" for item in passages[:3]
    )
    lang_note = "Reply in natural warm Hinglish/Hindi if the user used Hindi/Hinglish." if language.startswith("hi") else "Keep the tone warm, crisp, and spoken-friendly."
    content = _complete_json(
        system_prompt=(
            "You are SalesPilot AI, a helpful live voice sales assistant. Answer ONLY using the supplied source passages. "
            "Do not add facts, prices, integrations, guarantees, or policies not present in the passages. "
            "If the passage says an integration or capability is not confirmed, state clearly that it is not confirmed and suggest specialist verification. "
            "Include the source filename naturally (e.g. 'Source: product_faq.md'). Keep the reply concise (2-3 sentences max) for voice playback. "
            f"{lang_note} Return JSON with one string field named answer."
        ),
        user_prompt=f"Customer question: {question}\n\nApproved knowledge passages:\n{context}",
        history=history,
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


def answer_knowledge_base_query(
    question: str,
    passages: list[dict[str, Any]],
    fallback_chunks: list[dict[str, Any]] | None = None,
    language: str = "en-IN",
) -> dict[str, Any] | None:
    """Answer a knowledge-base search or FAQ query strictly from KB chunks via Gemini/LLM."""
    if not is_llm_configured():
        return None
    source_pool = passages[:4] if passages else (fallback_chunks or [])[:6]
    if not source_pool:
        return None
    context = "\n\n".join(
        f"SOURCE: {item.get('source')}\nPASSAGE: {item.get('content')}" for item in source_pool
    )
    lang_note = (
        "Match the user's language (English or Hinglish)."
        if language
        else "Reply in clear English or Hinglish matching the question."
    )
    content = _complete_json(
        system_prompt=(
            "You are the SalesPilot Knowledge Assistant. Answer the query STRICTLY using ONLY the supplied Knowledge Base passages. "
            "Do NOT invent capabilities, prices, integrations, or policies not explicitly written in the passages. "
            "If the passages clearly confirm something is NOT supported or NOT confirmed (such as native Shopify integration), set supported=true and state that clearly with the source. "
            "If the query asks about an unrelated topic not covered anywhere in the passages (for example, unrelated hardware or capabilities), set supported=false and explain it is not covered in the current knowledge base. "
            f"{lang_note} "
            'Return JSON ONLY: {"supported": true, "answer": "concise 1-3 sentence grounded answer", "sources": ["filename.md"]}'
        ),
        user_prompt=f"Query: {question}\n\nKnowledge Base Passages:\n{context}",
        temperature=0.1,
        timeout=14.0,
    )
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    supported = bool(parsed.get("supported", True))
    raw_sources = parsed.get("sources") if isinstance(parsed.get("sources"), list) else []
    valid_sources = {str(item.get("source")) for item in source_pool if item.get("source")}
    sources = [str(s) for s in raw_sources if str(s) in valid_sources]
    if supported and not sources and passages:
        sources = [str(passages[0].get("source"))]
    return {"supported": supported, "answer": answer.strip()[:2000], "sources": sources}


def generate_conversational_reply(
    customer_message: str,
    lead: dict[str, Any],
    next_question: str | None,
    captured_summary: str,
    language: str = "en-IN",
) -> str | None:
    """Optional model phrasing for natural voice turns; deterministic workflow stays authoritative."""
    if not is_llm_configured():
        return None
    lang_note = "Reply naturally in warm Hinglish or simple Hindi." if language.startswith("hi") else "Reply in warm, natural, spoken English (1 to 2 short sentences)."
    content = _complete_json(
        system_prompt=(
            "You are SalesPilot AI, a warm, articulate live voice sales assistant. Keep replies concise (under 40 words) "
            "with zero markdown or bullet points so they sound natural when spoken aloud. Never invent product prices, integrations, or commitments. "
            f"{lang_note} Return JSON: {{\"answer\": \"...\"}}."
        ),
        user_prompt=(
            f"Customer just said: {customer_message}\n"
            f"Lead name: {lead.get('name') or 'Customer'}\n"
            f"Facts captured this turn: {captured_summary or 'None'}\n"
            f"Next goal: {next_question or 'Ask if they would like to book a 30-minute product demo.'}"
        ),
        temperature=0.3,
        timeout=8.0,
    )
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    answer = parsed.get("answer") if isinstance(parsed, dict) else None
    return answer.strip()[:500] if isinstance(answer, str) and answer.strip() else None


def generate_smart_sales_turn(
    customer_message: str,
    lead: dict[str, Any],
    history: list[dict[str, str]],
    missing_fields: list[str],
    next_slots_summary: str,
    knowledge_summary: str,
    language: str = "en-IN",
) -> dict[str, Any] | None:
    """Single-roundtrip Gemini/LLM conversational turn + verbatim-quoted fact extraction."""
    if not is_llm_configured():
        return None

    lang_instruction = (
        "Match the customer's language automatically: if they speak Hindi or Hinglish, reply naturally in friendly conversational Hinglish (Latin script or light Hindi); otherwise reply in warm, natural Indian/global English."
    )
    system_prompt = (
        "You are SalesPilot AI, an intelligent, charismatic live voice sales agent (inspired by human-like voice assistants). "
        "Your job is to have a smooth, natural two-way voice conversation while qualifying the customer and guiding them to book a 30-minute demo.\n"
        "STRICT RULES:\n"
        "1. Keep your reply crisp, warm, and conversational (1-3 short sentences, <= 45 words, NO markdown, NO bullet lists, NO asterisks) so it sounds great spoken aloud.\n"
        "2. NEVER invent product prices, integrations (like Shopify), guarantees, or features not present in the Verified Product Context below.\n"
        "3. Ask for at most ONE missing qualification detail naturally (do not repeat facts already captured).\n"
        "4. Extract any NEW sales facts explicitly stated in the customer's latest message into `facts` ONLY when you can include an EXACT verbatim substring `quote` copied character-for-character from the customer's latest message.\n"
        "5. Allowed fields: name, company, requirement, budget_amount (integer INR), timeline_days (integer), decision_maker (boolean).\n"
        f"6. {lang_instruction}\n"
        'Return JSON ONLY: {"answer": "...", "facts": [{"field": "...", "value": ..., "quote": "..."}]}'
    )

    lead_snapshot = {
        "name": lead.get("name"),
        "company": lead.get("company"),
        "requirement": lead.get("requirement"),
        "budget_amount_inr": lead.get("budget_amount"),
        "timeline_days": lead.get("timeline_days"),
        "decision_maker": lead.get("decision_maker"),
        "current_score": lead.get("score", 0),
        "status": lead.get("status", "cold"),
    }
    user_prompt = (
        f"Current CRM Lead State: {json.dumps(lead_snapshot)}\n"
        f"Still missing qualification fields: {', '.join(missing_fields) or 'None — ready to offer a demo!'}\n"
        f"Upcoming Demo Slots (IST): {next_slots_summary}\n"
        f"Verified Product Context (never exceed these facts):\n{knowledge_summary}\n\n"
        f"Latest Customer Message ({language}): {customer_message}"
    )

    content = _complete_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history=history,
        temperature=0.35,
        timeout=15.0,
    )
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    facts = validate_fact_payload(customer_message, parsed)
    return {"answer": answer.strip()[:1200], "facts": facts}


def generate_handoff_reply(
    customer_message: str,
    reason: str,
    history: list[dict[str, str]] | None = None,
    language: str = "en-IN",
) -> str | None:
    if not is_llm_configured():
        return None
    content = _complete_json(
        system_prompt=(
            "You are SalesPilot AI. A customer needs a human representative or is upset. "
            "Acknowledge empathetically in 1-2 short spoken sentences, confirm you are flagging this for a human specialist with full context, and do not argue. "
            "Match English or Hinglish. Return JSON: {\"answer\": \"...\"}"
        ),
        user_prompt=f"Reason: {reason}\nCustomer message: {customer_message}",
        history=history,
        temperature=0.2,
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
