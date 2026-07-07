"""Objective function and metrics."""

from __future__ import annotations

import math
from typing import Any

from config import OBJECTIVE_WEIGHTS
from .models import Solution


def evaluate_solution(solution: Solution, context: dict[str, Any], runtime_seconds: float = 0.0, weights=OBJECTIVE_WEIGHTS) -> Solution:
    """Compute lexicographic-like objective and metrics for a weekly solution."""

    total_distance = sum(r.distance for r in solution.routes.values() if r.feasible)
    total_travel = sum(r.travel_time for r in solution.routes.values() if r.feasible)
    total_waiting = sum(r.waiting_time for r in solution.routes.values() if r.feasible)
    visits = [v for r in solution.routes.values() for v in r.visits if r.feasible]
    undelivered = len(set(context["customer_ids"]) - solution.delivered)
    delivered = len(solution.delivered)
    total_customers = len(context["customer_ids"])

    # Phạt hoãn = giao trễ hơn ngày đầu tiên khách có thể nhận hàng.
    first_day = context["first_available_day"]
    postponed = 0.0
    delivery_days = []
    for day, route in solution.routes.items():
        for customer in route.customers:
            delivery_days.append(day)
            postponed += max(0, day - first_day.get(customer, day))

    # Slack nhỏ nghĩa là lịch sát deadline; dùng 1/(slack+1) để phạt rủi ro nhưng không chia cho 0.
    slack_penalty = sum(1.0 / (max(0.0, v.slack) + 1.0) for v in visits) if context.get("use_slack_penalty", True) else 0.0
    min_slack = min((v.slack for v in visits), default=0.0)
    objective = (
        weights.undelivered * undelivered
        + weights.postponed * postponed
        + weights.distance * total_distance
        + weights.waiting * total_waiting
        + weights.slack * slack_penalty
    )
    metrics = {
        "objective": float(objective),
        "delivered_orders": delivered,
        "undelivered_orders": undelivered,
        "completion_rate": delivered / total_customers if total_customers else 0.0,
        "total_distance": float(total_distance),
        "total_travel_time": float(total_travel),
        "total_waiting_time": float(total_waiting),
        "postponement_penalty": float(postponed),
        "min_slack": float(min_slack if not math.isinf(min_slack) else 0.0),
        "average_delivery_day": float(sum(delivery_days) / len(delivery_days)) if delivery_days else 0.0,
        "runtime_seconds": float(runtime_seconds),
    }
    out = solution.copy()
    out.objective_value = float(objective)
    out.metrics = metrics
    return out
