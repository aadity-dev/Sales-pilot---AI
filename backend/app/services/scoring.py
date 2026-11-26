from __future__ import annotations

from typing import Any


def score_lead(lead: dict[str, Any]) -> tuple[int, str, list[dict[str, Any]]]:
    """Deterministic qualification: only explicit, stored facts contribute."""
    breakdown: list[dict[str, Any]] = []

    requirement = bool(lead.get("requirement"))
    breakdown.append({
        "criterion": "Clear business requirement",
        "points": 25 if requirement else 0,
        "maximum": 25,
        "reason": "A business requirement was explicitly captured." if requirement else "No explicit requirement has been captured yet.",
        "field": "requirement",
    })

    budget = lead.get("budget_amount")
    if budget is None:
        budget_points, budget_reason = 0, "Budget has not been explicitly stated."
    elif int(budget) >= 50000:
        budget_points, budget_reason = 25, "Stated budget meets the target qualification threshold of ₹50,000."
    else:
        budget_points, budget_reason = 15, "A budget was stated, but it is below the ₹50,000 target threshold."
    breakdown.append({
        "criterion": "Budget compatibility",
        "points": budget_points,
        "maximum": 25,
        "reason": budget_reason,
        "field": "budget_amount",
    })

    timeline = lead.get("timeline_days")
    if timeline is None:
        timeline_points, timeline_reason = 0, "Purchase timeline has not been explicitly stated."
    elif int(timeline) <= 30:
        timeline_points, timeline_reason = 25, "The stated purchase timeline is within 30 days."
    elif int(timeline) <= 90:
        timeline_points, timeline_reason = 15, "The stated purchase timeline is within 90 days."
    else:
        timeline_points, timeline_reason = 5, "The stated purchase timeline is more than 90 days away."
    breakdown.append({
        "criterion": "Purchase timeline",
        "points": timeline_points,
        "maximum": 25,
        "reason": timeline_reason,
        "field": "timeline_days",
    })

    decision = lead.get("decision_maker")
    if decision is True or decision == 1:
        decision_points, decision_reason = 25, "The customer explicitly confirmed decision-making authority."
    elif decision is False or decision == 0:
        decision_points, decision_reason = 0, "The customer explicitly said they are not the decision-maker."
    else:
        decision_points, decision_reason = 0, "Decision-making authority has not been established."
    breakdown.append({
        "criterion": "Decision-making authority",
        "points": decision_points,
        "maximum": 25,
        "reason": decision_reason,
        "field": "decision_maker",
    })

    score = min(100, sum(item["points"] for item in breakdown))
    status = "hot" if score >= 75 else "warm" if score >= 50 else "cold"
    return score, status, breakdown
