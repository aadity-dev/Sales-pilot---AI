from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..db import connect, new_id, utc_now
from .knowledge import retrieve
from .local_llm import extract_verified_facts, generate_conversational_reply, generate_grounded_answer
from .scoring import score_lead
from .voice import format_for_speech

INDIA_TZ = ZoneInfo("Asia/Kolkata")
DEMO_HOURS = [10, 11, 12, 14, 15, 16]

BUDGET_RE = re.compile(
    r"(?:₹\s*|inr\s*|rs\.?\s*)([\d,]+(?:\.\d+)?)|\b([\d,]+(?:\.\d+)?)\s*(?:rupees|inr|rs\.?|₹)\b",
    re.I,
)

HINDI_WORD_NUMBERS = {
    "ek": 1, "एक": 1,
    "do": 2, "दो": 2,
    "teen": 3, "तीन": 3,
    "chaar": 4, "char": 4, "चार": 4,
    "paanch": 5, "panch": 5, "पांच": 5, "पाँच": 5,
    "das": 10, "दस": 10,
    "bees": 20, "बीस": 20,
    "pachees": 25, "पच्चीस": 25,
    "tees": 30, "तीस": 30,
    "chalis": 40, "चालीस": 40,
    "pachas": 50, "पचास": 50,
    "saath": 60, "साठ": 60,
    "sattar": 70, "सत्तर": 70,
    "assi": 80, "अस्सी": 80,
    "nabbe": 90, "नब्बे": 90,
}

NON_NAME_WORDS = {
    "looking", "interested", "not sure", "a company", "frustrated", "angry", "upset",
    "calling", "here", "ready", "happy", "fine", "good", "doing", "the", "a", "an",
    "decision", "owner", "founder", "authorized", "authorised", "talking", "speaking",
    "based", "from", "working", "trying", "having", "facing", "asking", "wanting",
}

WEEKDAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _detect_language(message: str) -> str:
    if re.search(r"[\u0900-\u097F]", message):
        return "hi-IN"
    hinglish_markers = {"namaste", "namaskar", "kaise", "chahiye", "hazaar", "hajar", "karna", "hamara", "humko", "haan", "nahi", "bilkul", "baje", "kal", "mahine", "hafte"}
    words = set(re.findall(r"[a-z]+", message.lower()))
    if len(words & hinglish_markers) >= 1:
        return "hi-IN"
    return "en-IN"


def _parse_budget(message: str, asked_budget: bool = False) -> int | None:
    match = BUDGET_RE.search(message)
    if match:
        raw = match.group(1) or match.group(2)
        try:
            return int(float(raw.replace(",", "")))
        except ValueError:
            return None

    short = re.search(r"\b(\d+(?:\.\d+)?)\s*k\b", message, re.I)
    if short:
        return int(float(short.group(1)) * 1000)

    lakh = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|l)\b", message, re.I)
    if lakh:
        return int(float(lakh.group(1)) * 100_000)

    thousand = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:thousand|hazaar|hazar)\b", message, re.I)
    if thousand:
        return int(float(thousand.group(1)) * 1000)

    # Hindi / Devanagari number words paired with hazaar / lakh
    lower = message.lower()
    for word, val in HINDI_WORD_NUMBERS.items():
        if re.search(rf"(?:^|\s){re.escape(word)}\s+(?:hazaar|hazar|thousand|हज़ार|हजार)", lower):
            return val * 1000
        if re.search(rf"(?:^|\s){re.escape(word)}\s+(?:lakh|lakhs|lac|लाख)", lower):
            return val * 100_000

    # Plain number when explicitly discussing budget
    if asked_budget or re.search(r"\b(?:budget|spend|spending|cost|around|approx|approximately)\b", lower):
        plain = re.search(r"\b([\d,]{4,9})\b", message)
        if plain:
            try:
                num = int(plain.group(1).replace(",", ""))
                if 500 <= num <= 100_000_000:
                    return num
            except ValueError:
                pass
    return None


def _last_question_topic(last_agent_message: str | None) -> str | None:
    if not last_agent_message:
        return None
    lower = last_agent_message.lower()
    if any(k in lower for k in ["decision", "purchase decision", "decision-maker", "decision maker", "final say"]):
        return "decision_maker"
    if any(k in lower for k in ["budget", "spend"]):
        return "budget"
    if any(k in lower for k in ["when are you", "timeline", "implement", "launch", "start"]):
        return "timeline"
    if any(k in lower for k in ["challenge", "solve", "requirement", "automate", "help you with"]):
        return "requirement"
    if any(k in lower for k in ["demo", "slot", "appointment", "demonstration", "which time"]):
        return "booking"
    return None


def extract_facts(message: str, last_agent_message: str | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    topic = _last_question_topic(last_agent_message)
    lower = message.lower().strip()

    # Name & Company (case-sensitive on captured entity to avoid pulling common lowercase words)
    name_match = re.search(
        r"\b(?:[Mm]y name is|[Ii] am|[Ii]'m|[Tt]his is|[Mm]yself)\s+([A-Z][a-z]{1,25}(?:\s+[A-Z][a-z]{1,25}){0,2})",
        message,
    )
    if name_match:
        value = name_match.group(1).strip(" .,!?")
        first_word = value.split()[0].lower()
        if value and value.lower() not in NON_NAME_WORDS and first_word not in NON_NAME_WORDS:
            facts["name"] = value

    company_match = re.search(
        r"\b(?:[Ii] work at|[Ii] work for|[Cc]ompany is|[Oo]ur company is|[Cc]alling from|[Ff]rom)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})",
        message,
    )
    if company_match:
        value = company_match.group(1).strip(" .,!?")
        if value and value.lower() not in NON_NAME_WORDS:
            facts["company"] = value

    # Requirements
    requirement_terms = [
        "customer support automation", "automate customer support", "support automation",
        "lead generation", "sales automation", "voice automation", "appointment booking",
        "customer service automation", "automate calls", "reduce support workload",
        "whatsapp automation", "order tracking", "inbound sales", "outbound calling",
    ]
    for term in requirement_terms:
        if term in lower:
            facts["requirement"] = term
            break

    if "requirement" not in facts:
        req_patterns = [
            r"(?:need|looking for|looking to|want to|require|trying to|hoping to|help with|struggling with|problem is|challenge is)\s+([^.!?]{5,110})",
            r"(?:automate|manage|handle)\s+(?:our|my|the)?\s*([^.!?]{4,90})",
            r"(?:हमको|मुझे|हमें)\s+([^.!?]{4,90}?)\s*(?:चाहिए|करना है)",
            r"\b(?:humko|mujhe|hamein|hume)\s+([a-z0-9\s-]{4,80}?)\s+(?:chahiye|karna hai)",
        ]
        for pattern in req_patterns:
            match = re.search(pattern, message, re.I)
            if match:
                candidate = match.group(1).strip(" ,.!?")
                if (
                    candidate
                    and candidate.lower() not in {"a demo", "product demo", "book a demo", "talk to someone", "a human", "approval", "manager approval", "boss approval"}
                    and not re.search(r"\b(?:manager|boss|partner)'?s?\s+approval\b", candidate, re.I)
                ):
                    facts["requirement"] = candidate[:120]
                    break

    # Contextual bare requirement reply if agent asked for business challenge
    if "requirement" not in facts and topic == "requirement":
        cleaned = re.sub(r"^(?:yes|yeah|well|actually|so|basically|hi|hello)[,\s]+", "", lower).strip(" .!?")
        if (
            len(cleaned.split()) >= 3
            and "?" not in message
            and not is_greeting(message)
            and not wants_human(message)
            and _parse_budget(message) is None
        ):
            facts["requirement"] = message.strip(" .!?")[:120]

    # Budget
    budget = _parse_budget(message, asked_budget=(topic == "budget"))
    if budget is not None:
        facts["budget_amount"] = budget

    # Timeline
    timeline_patterns = [
        (r"(?:within|in|next)?\s*(?:the\s+)?(?:next\s+)?(\d+)\s+days?", None),
        (r"(?:within|in|next)?\s*(?:the\s+)?(?:next\s+)?(\d+)\s+weeks?", None),
        (r"(?:within|in|next)?\s*(?:the\s+)?(?:next\s+)?(\d+)\s+months?", None),
        (r"within\s+(?:one|a)\s+month|in\s+(?:one|a)\s+month|this\s+month|next\s+month|agle\s+mahine|एक\s+महीने", 30),
        (r"within\s+(?:the\s+)?(?:next\s+)?90\s+days?|in\s+three\s+months|next\s+quarter|this\s+quarter", 90),
        (r"next\s+week|within\s+a\s+week|this\s+week|agle\s+hafte|अगले\s+हफ्ते", 7),
        (r"asap|as\s+soon\s+as\s+possible|immediately|right\s+away|urgent|turant|jaldi|अभी|तुरंत", 7),
        (r"within\s+six\s+months|in\s+6\s+months|half\s+year", 180),
        (r"\btomorrow\b|\bkal\b", 1),
    ]
    for pattern, days in timeline_patterns:
        match = re.search(pattern, lower)
        if match:
            if days is None:
                quantity = re.search(r"(\d+)\s+(days?|weeks?|months?)", match.group(0))
                if quantity:
                    n = int(quantity.group(1))
                    unit = quantity.group(2)
                    days = n * (30 if unit.startswith("month") else 7 if unit.startswith("week") else 1)
                else:
                    days = 14
            # Avoid turning "next 30 days" in unrelated appointment phrases unless valid timeline
            if days > 0:
                facts["timeline_days"] = days
                break

    # Decision-maker
    if re.search(
        r"\b(i am|i'm|yes,?\s*i am|i make|i have|i take|main hi)\b.{0,40}\b(owner|founder|ceo|cto|director|decision[\s-]?maker|final decision|final say|authorized|authorised|decide|call)\b",
        lower,
    ) or re.search(r"\b(it'?s my call|i decide|i am the one who decides|final authority)\b", lower):
        facts["decision_maker"] = True
    elif re.search(
        r"\b(i am not|i'm not|not the|my manager|my boss|need approval|have to ask|manager se|team decides)\b.{0,40}\b(decision[\s-]?maker|owner|authorized|authorised|approve|approval|boss|manager|puchna)\b",
        lower,
    ) or re.search(
        r"\b(not the decision[\s-]?maker|need\s+(?:my\s+)?(?:boss|manager|partner|team)'?s?\s*approval|i\s+don'?t\s+decide)\b",
        lower,
    ):
        facts["decision_maker"] = False
    elif topic == "decision_maker":
        stripped = re.sub(r"[^\w\s\u0900-\u097F]", "", lower).strip()
        if re.fullmatch(r"(?:yes|yeah|yup|sure|definitely|absolutely|of course|correct|i am|yes i am|yeah i am|haan|haanji|ha|ji|bilkul|हाँ|जी|बिल्कुल)(?:\s+i\s+am)?", stripped):
            facts["decision_maker"] = True
        elif re.match(r"^(?:no|nope|not really|not me|nahi|na|नहीं)\b", stripped):
            facts["decision_maker"] = False

    return facts


def is_greeting(message: str) -> bool:
    normalized = re.sub(r"[^\w\s\u0900-\u097F]", "", message.lower()).strip()
    return bool(
        re.match(r"^(hi|hello|hey|namaste|namaskar|नमस्ते|नमस्कार)\b", normalized)
        or re.fullmatch(
            r"(good morning|good afternoon|good evening|how are you(?: doing)?|kaise ho|kya haal hai|नमस्ते|नमस्कार|कैसे हो|कैसे हैं)(?:\s+salespilot)?",
            normalized,
        )
    )


def _next_qualification_question(lead: dict[str, Any], lang: str = "en-IN") -> str | None:
    if lang.startswith("hi"):
        if not lead.get("requirement"):
            return "Aap apne business mein kaunsa workflow ya customer problem solve karna chahte hain?"
        if lead.get("budget_amount") is None:
            return "Iske liye aapka lagbhag kitna budget hai?"
        if lead.get("timeline_days") is None:
            return "Aap yeh solution kab tak start karna chahte hain?"
        if lead.get("decision_maker") is None:
            return "Kya final decision aap lete hain?"
        return None
    if not lead.get("requirement"):
        return "What business challenge or workflow are you hoping to automate?"
    if lead.get("budget_amount") is None:
        return "Do you have an approximate budget in mind for this?"
    if lead.get("timeline_days") is None:
        return "What timeline are you aiming for to get started?"
    if lead.get("decision_maker") is None:
        return "Are you involved in the final purchase decision?"
    return None


def classify_sentiment(message: str) -> str:
    lower = message.lower()
    negative = ["angry", "frustrated", "upset", "terrible", "bad experience", "waste of time", "unacceptable", "ridiculous", "hate", "annoyed", "useless"]
    positive = ["great", "excellent", "interested", "love", "sounds good", "thank you", "thanks", "perfect", "awesome", "wonderful", "helpful", "nice"]
    if any(term in lower for term in negative):
        return "negative"
    if any(term in lower for term in positive):
        return "positive"
    return "neutral"


def wants_human(message: str) -> bool:
    lower = message.lower()
    return any(
        term in lower
        for term in [
            "human", "real person", "sales representative", "talk to someone",
            "agent please", "manager", "speak to a person", "transfer me", "connect me to someone",
        ]
    )


def is_knowledge_question(message: str) -> bool:
    lower = message.lower()
    terms = [
        "price", "pricing", "cost", "how much", "feature", "integrat", "shopify",
        "product", "plan", "support", "language", "security", "data", "does your",
        "do you offer", "can your", "what are you", "what do you", "what can you",
        "what are we", "what will you", "what is salespilot", "what is this",
    ]
    product_subject = any(
        term in lower
        for term in [
            "salespilot", "your product", "your platform", "your system",
            "you offer", "you support", "you integrate", "your pricing", "your price",
        ]
    )
    capability_question = lower.strip().startswith((
        "what are you", "what do you", "what can you", "what will you",
        "what is your", "what is the", "how does", "does your", "can your",
        "do you", "is your",
    ))
    explicit_product_term = any(term in lower for term in terms)
    customer_need = any(term in lower for term in ["i need", "we need", "looking for", "we want", "i want", "our requirement"])
    return capability_question or product_subject or (explicit_product_term and not customer_need)


def _upsert_evidence(conn, lead_id: str, call_id: str, field: str, value: Any, quote: str) -> None:
    conn.execute(
        """INSERT INTO evidence (id, lead_id, call_id, field, value, quote, status, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'verified', 1.0, ?)
           ON CONFLICT(lead_id, field) DO UPDATE SET
             call_id=excluded.call_id, value=excluded.value, quote=excluded.quote,
             status='verified', confidence=1.0, created_at=excluded.created_at""",
        (new_id("ev"), lead_id, call_id, field, str(value), quote, utc_now()),
    )


def get_lead(conn, lead_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def get_evidence(conn, lead_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM evidence WHERE lead_id = ? ORDER BY created_at DESC", (lead_id,)).fetchall()
    return [dict(row) for row in rows]


def summarize_messages(messages: list[str], lead: dict[str, Any]) -> str:
    customer_messages = [m for m in messages if m]
    latest = customer_messages[-3:]
    parts = []
    if lead.get("requirement"):
        parts.append(f"Requirement: {lead['requirement']}")
    if lead.get("budget_amount") is not None:
        parts.append(f"Budget stated: ₹{int(lead['budget_amount']):,}")
    if lead.get("timeline_days") is not None:
        parts.append(f"Timeline: {lead['timeline_days']} days")
    if lead.get("decision_maker") is not None:
        parts.append(f"Decision-maker: {'yes' if lead['decision_maker'] else 'no'}")
    if latest:
        parts.append("Recent conversation: " + " | ".join(latest))
    return "; ".join(parts) if parts else "The conversation has started. More qualification information is needed."


def _parse_booking_datetime(message: str) -> tuple[date | None, int | None]:
    lower = message.lower()
    now_ist = datetime.now(INDIA_TZ)
    target_date: date | None = None

    if "today" in lower or "aaj" in lower:
        target_date = now_ist.date()
    elif "tomorrow" in lower or "kal" in lower:
        target_date = now_ist.date() + timedelta(days=1)
    else:
        iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", lower)
        if iso_match:
            try:
                target_date = date.fromisoformat(iso_match.group(1))
            except ValueError:
                target_date = None
        if target_date is None:
            for name, wd in WEEKDAY_NAMES.items():
                if re.search(rf"\b{name}\b", lower):
                    delta = (wd - now_ist.weekday()) % 7
                    if delta == 0:
                        delta = 7
                    target_date = now_ist.date() + timedelta(days=delta)
                    break

    hour: int | None = None
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)?\b", lower)
    if time_match and (time_match.group(3) or time_match.group(2) is not None or "at " in lower):
        raw_hour = int(time_match.group(1))
        meridiem = time_match.group(3)
        if meridiem == "pm" and 1 <= raw_hour <= 11:
            raw_hour += 12
        elif meridiem == "baje" and 1 <= raw_hour <= 6:
            raw_hour += 12
        elif meridiem is None and 1 <= raw_hour <= 5:
            raw_hour += 12
        hour = raw_hour

    return target_date, hour


def _available_slots_for_date(conn, target_date: date) -> list[dict[str, Any]]:
    if target_date.weekday() >= 5:
        return []
    day_start = datetime.combine(target_date, time.min, tzinfo=INDIA_TZ).astimezone(timezone.utc)
    day_end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=INDIA_TZ).astimezone(timezone.utc)
    booked = conn.execute(
        """SELECT start_time, end_time FROM appointments
           WHERE status='booked' AND start_time < ? AND end_time > ?""",
        (day_end.isoformat(timespec="seconds"), day_start.isoformat(timespec="seconds")),
    ).fetchall()
    booked_ranges = [(datetime.fromisoformat(r["start_time"]), datetime.fromisoformat(r["end_time"])) for r in booked]
    now_utc = datetime.now(timezone.utc)
    slots: list[dict[str, Any]] = []
    for hour in DEMO_HOURS:
        local_start = datetime.combine(target_date, time(hour, 0), tzinfo=INDIA_TZ)
        start_utc = local_start.astimezone(timezone.utc)
        end_utc = start_utc + timedelta(minutes=30)
        if start_utc <= now_utc:
            continue
        if not any(start_utc < end and end_utc > start for start, end in booked_ranges):
            slots.append({
                "hour": hour,
                "start_time": local_start.isoformat(),
                "start_utc": start_utc.isoformat(timespec="seconds"),
                "end_utc": end_utc.isoformat(timespec="seconds"),
                "label": local_start.strftime("%-I:%M %p"),
            })
    return slots


def _next_weekday(after_date: date) -> date:
    candidate = after_date
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _handle_booking_intent(
    conn,
    lead_id: str,
    message: str,
    last_agent_message: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    lower = message.lower()
    topic = _last_question_topic(last_agent_message)
    booking_keywords = [
        "book a demo", "book demo", "book an appointment", "schedule a demo",
        "schedule demo", "arrange a demo", "available slots", "available times",
        "open slots", "free slots", "book for", "book slot", "book tomorrow",
        "schedule for", "demo slot",
    ]
    explicit_booking = any(k in lower for k in booking_keywords)
    contextual_booking = topic == "booking" and (
        bool(re.search(r"\b(yes|yeah|sure|please|book|schedule|tomorrow|today|am|pm|baje|\d{1,2})\b", lower))
    )
    # Don't hijack general pricing/FAQ questions like "how does appointment booking work?"
    if is_knowledge_question(message) and not explicit_booking:
        return None, None
    if not (explicit_booking or contextual_booking):
        return None, None

    target_date, hour = _parse_booking_datetime(message)
    if target_date is None:
        target_date = _next_weekday(datetime.now(INDIA_TZ).date() + timedelta(days=1))

    slots = _available_slots_for_date(conn, target_date)
    day_label = target_date.strftime("%A, %d %b")

    if hour is not None:
        matching = next((s for s in slots if s["hour"] == hour), None)
        if matching:
            appt_id = new_id("appt")
            idem = f"chat:{lead_id}:{matching['start_utc']}"
            existing = conn.execute("SELECT * FROM appointments WHERE idempotency_key=?", (idem,)).fetchone()
            if existing:
                appt = dict(existing)
            else:
                conn.execute(
                    """INSERT INTO appointments
                       (id, lead_id, start_time, end_time, status, idempotency_key, notes, created_at)
                       VALUES (?, ?, ?, ?, 'booked', ?, ?, ?)""",
                    (appt_id, lead_id, matching["start_utc"], matching["end_utc"], idem, "Booked via SalesPilot voice/chat agent", utc_now()),
                )
                appt = dict(conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone())
            reply = f"Done! I've booked your 30-minute product demonstration for {day_label} at {matching['label']} IST. Is there anything else you'd like to ask before then?"
            return reply, appt

        if slots:
            labels = ", ".join(s["label"] for s in slots[:4])
            return f"That time isn't available on {day_label}. Open slots on {day_label} are {labels} IST — which one works best for you?", None
        next_day = _next_weekday(target_date + timedelta(days=1))
        next_slots = _available_slots_for_date(conn, next_day)
        labels = ", ".join(s["label"] for s in next_slots[:4])
        return f"We don't have open slots on {day_label} (demos run weekdays 10 AM–4 PM IST). On {next_day.strftime('%A, %d %b')}, {labels} IST are open. Want me to book one of those?", None

    if not slots:
        target_date = _next_weekday(target_date + timedelta(days=1))
        slots = _available_slots_for_date(conn, target_date)
        day_label = target_date.strftime("%A, %d %b")
    labels = ", ".join(s["label"] for s in slots[:4])
    return f"I'd be happy to set that up! On {day_label}, we have demo slots open at {labels} IST. Which time works best for you?", None


def _acknowledge_captured_facts(new_facts: dict[str, Any], lang: str) -> str:
    parts: list[str] = []
    if "requirement" in new_facts:
        parts.append(f"need for {new_facts['requirement']}")
    if "budget_amount" in new_facts:
        parts.append(f"₹{int(new_facts['budget_amount']):,} budget")
    if "timeline_days" in new_facts:
        days = int(new_facts["timeline_days"])
        parts.append("7-day timeline" if days == 7 else f"{days}-day timeline")
    if "decision_maker" in new_facts:
        parts.append("decision-maker confirmation" if new_facts["decision_maker"] else "team approval needed")
    if not parts:
        return ""
    joined = ", ".join(parts[:-1]) + (f" and {parts[-1]}" if len(parts) > 1 else parts[0])
    if lang.startswith("hi"):
        return f"Samajh gaya — maine aapka {joined} note kar liya hai."
    return f"Got it — I've noted your {joined}."


def process_message(
    db_path: str,
    lead_id: str,
    message: str,
    call_id: str | None = None,
    language: str = "en-IN",
) -> dict[str, Any]:
    clean_message = message.strip()
    if not clean_message:
        raise ValueError("Message cannot be empty.")

    detected_lang = _detect_language(clean_message)
    effective_lang = "hi-IN" if (detected_lang == "hi-IN" or language.startswith("hi")) else "en-IN"

    with connect(db_path) as conn:
        lead = get_lead(conn, lead_id)
        if not lead:
            raise LookupError("Lead not found.")
        if call_id:
            call = conn.execute("SELECT id FROM calls WHERE id = ? AND lead_id = ?", (call_id, lead_id)).fetchone()
            if not call:
                raise LookupError("Call session not found for this lead.")
        else:
            call_id = new_id("call")
            conn.execute(
                "INSERT INTO calls (id, lead_id, started_at, language) VALUES (?, ?, ?, ?)",
                (call_id, lead_id, utc_now(), effective_lang),
            )

        last_agent_row = conn.execute(
            "SELECT content FROM messages WHERE call_id=? AND role='agent' ORDER BY created_at DESC LIMIT 1",
            (call_id,),
        ).fetchone()
        last_agent_message = last_agent_row[0] if last_agent_row else None

        conn.execute(
            "INSERT INTO messages (id, call_id, role, content, created_at) VALUES (?, ?, 'customer', ?, ?)",
            (new_id("msg"), call_id, clean_message, utc_now()),
        )

        facts = extract_facts(clean_message, last_agent_message=last_agent_message)
        evidence_quotes = {field: clean_message for field in facts}
        local_model_facts = extract_verified_facts(clean_message)
        # Rule-based extraction takes precedence. Local LLM may supplement with verbatim quote only.
        for field, item in local_model_facts.items():
            if field not in facts:
                facts[field] = item["value"]
                evidence_quotes[field] = item["quote"]

        newly_captured: dict[str, Any] = {}
        for field, value in facts.items():
            if field in {"name", "company", "requirement", "budget_amount", "timeline_days", "decision_maker"}:
                if lead.get(field) != value:
                    newly_captured[field] = value
                lead[field] = value
                _upsert_evidence(conn, lead_id, call_id, field, value, evidence_quotes.get(field, clean_message))

        score, status, breakdown = score_lead(lead)
        conn.execute(
            """UPDATE leads SET name=?, company=?, requirement=?, budget_amount=?, timeline_days=?,
               decision_maker=?, score=?, status=?, updated_at=? WHERE id=?""",
            (
                lead.get("name"), lead.get("company"), lead.get("requirement"), lead.get("budget_amount"),
                lead.get("timeline_days"), lead.get("decision_maker"), score, status, utc_now(), lead_id,
            ),
        )

        sentiment = classify_sentiment(clean_message)
        human_request = wants_human(clean_message)
        angry = sentiment == "negative"
        handoff = human_request or angry
        handoff_reason = (
            "Customer requested a human representative."
            if human_request
            else "Negative customer sentiment detected; human follow-up recommended."
            if angry
            else ""
        )
        citations: list[dict[str, Any]] = []
        appointment_booked: dict[str, Any] | None = None
        response = ""
        model_used = bool(local_model_facts)

        first_name = (lead.get("name") or "").split()[0] if lead.get("name") else ""

        if handoff:
            response = "I understand. I'll flag this conversation for a human sales representative and pass along the context so you don't have to repeat yourself."
        elif is_greeting(clean_message) and not newly_captured:
            if effective_lang.startswith("hi"):
                response = f"Namaste{' ' + first_name if first_name else ''}! Main SalesPilot AI hoon. Aaj aap apne business mein kya automate karna chahte hain?"
            else:
                question = _next_qualification_question(lead, effective_lang)
                response = f"Hi{' ' + first_name if first_name else ''}! I’m SalesPilot, doing great thanks for asking. {question or 'How can I help you today?'}"
        elif any(phrase in clean_message.lower() for phrase in ["मुझे नहीं पता", "मुझे नहीं समझ", "i don't know", "i do not know", "not sure", "pata nahi"]):
            question = _next_qualification_question(lead, effective_lang)
            response = (
                f"No problem at all. We can take it one step at a time. {question}"
                if question
                else "No problem at all. We already have the key details — would you like me to check available demo slots?"
            )
        else:
            booking_reply, appointment_booked = _handle_booking_intent(conn, lead_id, clean_message, last_agent_message)
            if booking_reply:
                response = booking_reply
            elif is_knowledge_question(clean_message):
                generic_product_question = any(
                    term in clean_message.lower()
                    for term in ["what are you", "what do you", "what can you", "what are we", "what will you", "what is this", "tell me about salespilot"]
                )
                retrieval_query = "SalesPilot AI product overview capabilities" if generic_product_question else clean_message
                matches = retrieve(db_path, retrieval_query, limit=2)
                if matches:
                    first = matches[0]
                    spoken_content = re.sub(r"^#{1,6}\s+.*$", "", str(first["content"]), flags=re.MULTILINE).strip()
                    response = f"{spoken_content}\n\nSource: {first['source']}."
                    citations = [{"source": item["source"], "content": item["content"], "score": item["score"]} for item in matches]
                    model_answer = generate_grounded_answer(clean_message, matches)
                    if model_answer:
                        response = model_answer
                        model_used = True
                else:
                    response = "I don't have verified information for that question in the current knowledge base. I don't want to guess, so I've flagged this for a product specialist to follow up."
                    handoff = True
                    handoff_reason = "The knowledge base did not contain verified support for the customer's question."
            else:
                question = _next_qualification_question(lead, effective_lang)
                ack = _acknowledge_captured_facts(newly_captured, effective_lang)
                llm_reply = generate_conversational_reply(
                    clean_message, lead, question, ack, language=effective_lang
                )
                if llm_reply:
                    response = llm_reply
                    model_used = True
                elif ack and question:
                    response = f"{ack} {question}"
                elif ack and not question:
                    response = f"{ack} Your profile is now fully qualified at {score}/100 ({status.upper()}). Would you like to book a 30-minute demo slot?"
                elif question:
                    response = f"Thanks for sharing that. {question}"
                else:
                    response = f"Thanks{' ' + first_name if first_name else ''}! We have all the key details ({score}/100). Would you like me to check available slots for a 30-minute product demonstration?"

        conn.execute(
            "INSERT INTO messages (id, call_id, role, content, created_at) VALUES (?, ?, 'agent', ?, ?)",
            (new_id("msg"), call_id, response, utc_now()),
        )
        conn.execute(
            "UPDATE calls SET sentiment=?, handoff_required=?, handoff_reason=?, language=? WHERE id=?",
            (sentiment, 1 if handoff else 0, handoff_reason, effective_lang, call_id),
        )
        messages = [
            row[0]
            for row in conn.execute("SELECT content FROM messages WHERE call_id=? AND role='customer' ORDER BY created_at", (call_id,)).fetchall()
        ]
        summary = summarize_messages(messages, lead)
        conn.execute("UPDATE calls SET summary=? WHERE id=?", (summary, call_id))
        refreshed_lead = get_lead(conn, lead_id) or lead
        evidence = get_evidence(conn, lead_id)

    return {
        "call_id": call_id,
        "response": response,
        "spoken_response": format_for_speech(response),
        "detected_language": effective_lang,
        "lead": refreshed_lead,
        "score_breakdown": breakdown,
        "evidence": evidence,
        "sentiment": sentiment,
        "handoff_required": handoff,
        "handoff_reason": handoff_reason,
        "summary": summary,
        "citations": citations,
        "appointment_booked": appointment_booked,
        "response_mode": "local_model_assisted" if model_used else "deterministic_local",
    }


def create_call(db_path: str, lead_id: str, language: str = "en-IN") -> dict[str, Any]:
    with connect(db_path) as conn:
        if not conn.execute("SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone():
            raise LookupError("Lead not found.")
        call_id = new_id("call")
        conn.execute(
            "INSERT INTO calls (id, lead_id, started_at, language) VALUES (?, ?, ?, ?)",
            (call_id, lead_id, utc_now(), language),
        )
        return dict(conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone())
