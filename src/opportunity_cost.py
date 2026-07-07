"""Opportunity Cost of Postponement calculations."""

from __future__ import annotations

from typing import Any

from .feasibility import best_insertion_positions


def compute_remaining_windows(customer_id: str, current_day: int, context: dict[str, Any]) -> int:
    """Count remaining valid receiving windows from current day to Sunday."""

    # Khach cang it cua so con lai cang kem linh hoat, nen can uu tien som.
    return sum(len(context["tw_index"].get((customer_id, day), [])) for day in context["days"] if day >= current_day)


def compute_conflict_pressure(customer_id: str, day: int, context: dict[str, Any]) -> float:
    """Estimate how crowded the customer's windows are on a day."""

    windows = context["tw_index"].get((customer_id, day), [])
    if not windows:
        return 0.0
    pressure = 0.0
    for start, end in windows:
        length = max(1, end - start)
        overlaps = 0
        for (other, other_day), other_windows in context["tw_index"].items():
            if other == customer_id or other_day != day:
                continue
            if any(max(start, os) < min(end, oe) for os, oe in other_windows):
                overlaps += 1
        pressure += overlaps / length
    return pressure / len(windows)


def _best_cost_for_days(customer_id: str, solution, days: list[int], context: dict[str, Any]) -> float | None:
    """Return the best feasible insertion cost across chosen days."""

    positions = best_insertion_positions(solution, customer_id, context, days=days, limit=1)
    return positions[0]["cost"] if positions else None


def compute_feasibility_opportunity_cost(customer_id: str, solution, current_day: int, context: dict[str, Any]) -> float:
    """Compute OC from losing future feasible insertion options."""

    today = _best_cost_for_days(customer_id, solution, [current_day], context)
    future_days = [d for d in context["days"] if d > current_day]
    future = _best_cost_for_days(customer_id, solution, future_days, context)
    if today is None:
        today = context["large_penalty"]
    if future is None:
        future = context["large_penalty"]
    # Neu tuong lai khong con vi tri kha thi, hoan don co rui ro that bai rat cao.
    return float(future - today)


def compute_lateness_opportunity_cost(customer_id: str, delivery_day: int, context: dict[str, Any]) -> float:
    """Compute lateness relative to the customer's first available day."""

    first_day = context["first_available_day"].get(customer_id, delivery_day)
    # Tach lateness ra khoi feasibility OC de tranh viec OC day don sang ngay muon hon.
    return float(max(0, delivery_day - first_day))


def compute_postponement_increment(customer_id: str, delivery_day: int, context: dict[str, Any]) -> float:
    """Return the objective postponement increment for assigning customer to delivery_day."""

    return compute_lateness_opportunity_cost(customer_id, delivery_day, context)


def compute_opportunity_cost(customer_id: str, solution, current_day: int, context: dict[str, Any]) -> float:
    """Backward-compatible alias for feasibility opportunity cost."""

    return compute_feasibility_opportunity_cost(customer_id, solution, current_day, context)


def compute_opportunity_index(customer_id: str, solution, current_day: int, context: dict[str, Any], insertion_cost: float = 0.0) -> float:
    """Compute a normalized urgency/inflexibility score for prioritization."""

    remaining = compute_remaining_windows(customer_id, current_day, context)
    windows_today_and_future = [
        w
        for day in context["days"]
        if day >= current_day
        for w in context["tw_index"].get((customer_id, day), [])
    ]
    nearest_close = min((end for _start, end in windows_today_and_future), default=24 * 60)
    urgency = max(0.0, (24 * 60 - nearest_close) / (24 * 60))
    inflexibility = 1.0 / max(1, remaining)
    postponement_risk = current_day / 7.0
    conflict = compute_conflict_pressure(customer_id, current_day, context)
    normalized_cost = min(1.0, max(0.0, insertion_cost / 1000.0))
    # Khach xa nhung sap het cua so van can uu tien hon khach gan con nhieu ngay.
    return 0.30 * urgency + 0.30 * inflexibility + 0.20 * postponement_risk + 0.15 * conflict - 0.05 * normalized_cost


def compute_all_opportunity_costs(solution, candidate_customers: list[str], current_day: int, context: dict[str, Any]) -> dict[str, float]:
    """Compute feasibility opportunity cost for many customers."""

    return {c: compute_feasibility_opportunity_cost(c, solution, current_day, context) for c in candidate_customers}
