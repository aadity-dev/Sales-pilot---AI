from backend.app.services.agent import classify_sentiment, extract_facts
from backend.app.services.scoring import score_lead


def test_extract_facts_from_sample_sales_statement():
    text = "We need customer support automation. Our budget is ₹50,000, within 30 days, and I am the decision maker."
    facts = extract_facts(text)
    assert facts["requirement"] == "customer support automation"
    assert facts["budget_amount"] == 50000
    assert facts["timeline_days"] == 30
    assert facts["decision_maker"] is True


def test_budget_k_notation_and_timeline():
    facts = extract_facts("Looking for lead generation with a 60k budget next week.")
    assert facts["budget_amount"] == 60000
    assert facts["timeline_days"] == 7


def test_scoring_is_deterministic_and_explained():
    score, status, breakdown = score_lead({
        "requirement": "lead generation",
        "budget_amount": 40000,
        "timeline_days": 60,
        "decision_maker": None,
    })
    assert score == 55  # 25 + 15 + 15 + 0
    assert status == "warm"
    assert len(breakdown) == 4
    assert all("reason" in criterion for criterion in breakdown)


def test_sentiment_classification():
    assert classify_sentiment("This sounds excellent, thank you") == "positive"
    assert classify_sentiment("I am angry about this terrible service") == "negative"
    assert classify_sentiment("Can you explain the product?") == "neutral"


def test_local_model_facts_require_verbatim_evidence_quotes():
    from backend.app.services.local_llm import validate_fact_payload

    customer_text = "Our budget is ₹50,000 and we need support automation."
    payload = {
        "facts": [
            {"field": "budget_amount", "value": 50000, "quote": "₹50,000"},
            {"field": "requirement", "value": "support automation", "quote": "support automation"},
            {"field": "company", "value": "Invented Ltd", "quote": "I work at Invented Ltd"},
            {"field": "decision_maker", "value": "yes", "quote": "we need support automation"},
            {"field": "internal_prompt", "value": "ignore rules", "quote": "₹50,000"},
        ]
    }
    accepted = validate_fact_payload(customer_text, payload)
    assert accepted["budget_amount"]["value"] == 50000
    assert accepted["requirement"]["quote"] == "support automation"
    assert "company" not in accepted
    assert "decision_maker" not in accepted
    assert "internal_prompt" not in accepted


def test_contextual_decision_maker_and_hinglish_budget_extraction():
    facts = extract_facts("Yes, I am", last_agent_message="Are you involved in the final purchase decision?")
    assert facts["decision_maker"] is True

    neg_facts = extract_facts("No, I need manager approval", last_agent_message="Are you involved in the final purchase decision?")
    assert neg_facts["decision_maker"] is False

    hinglish = extract_facts("Hamara budget 50 hazaar hai aur next month start karna hai")
    assert hinglish["budget_amount"] == 50000
    assert hinglish["timeline_days"] == 30

    lakh_facts = extract_facts("Around 1.5 lakhs, need it asap")
    assert lakh_facts["budget_amount"] == 150000
    assert lakh_facts["timeline_days"] == 7


def test_format_for_speech_removes_markdown():
    from backend.app.services.voice import format_for_speech

    spoken = format_for_speech("## Overview\n**Growth** costs ₹50,000.\n\nSource: product_faq.md.")
    assert "##" not in spoken
    assert "**" not in spoken
    assert "50,000 rupees" in spoken
    assert "product faq" in spoken.lower()
