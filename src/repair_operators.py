"""Repair operators for ALNS."""

from __future__ import annotations

import logging
import random
from typing import Any

from .feasibility import apply_insertion, best_insertion_positions
from .objective import evaluate_solution
from .opportunity_cost import compute_feasibility_opportunity_cost, compute_opportunity_index, compute_postponement_increment


def _finish(solution, removed: list[str], context: dict[str, Any]):
    """Ensure leftover customers are marked unassigned."""

    out = solution.copy()
    for c in removed:
        if c not in out.delivered:
            out.unassigned.add(c)
    return out


def cheapest_insertion(solution, removed: list[str], context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Repeatedly insert the globally cheapest feasible customer-position pair."""

    out = solution.copy()
    pending = list(removed)
    while pending:
        best = None
        for c in pending:
            positions = best_insertion_positions(out, c, context, limit=1)
            if positions and (best is None or positions[0]["cost"] < best["insertion"]["cost"]):
                best = {"customer": c, "insertion": positions[0]}
        if best is None:
            break
        out = apply_insertion(out, best["insertion"], context)
        pending.remove(best["customer"])
    return _finish(out, pending, context)


def regret2_insertion(solution, removed: list[str], context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Insert customers by largest regret-2 value."""

    return _regret_insertion(solution, removed, context, k=2)


def regret3_insertion(solution, removed: list[str], context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Insert customers by largest regret-3 value."""

    return _regret_insertion(solution, removed, context, k=3)


def _regret_insertion(solution, removed: list[str], context: dict[str, Any], k: int):
    """Shared regret insertion routine."""

    out = solution.copy()
    pending = list(removed)
    while pending:
        best_choice = None
        for c in pending:
            positions = best_insertion_positions(out, c, context, limit=k)
            if not positions:
                continue
            best_cost = positions[0]["cost"]
            kth_cost = positions[-1]["cost"] if len(positions) >= k else context["large_penalty"]
            regret = kth_cost - best_cost
            if best_choice is None or regret > best_choice["score"]:
                best_choice = {"customer": c, "insertion": positions[0], "score": regret}
        if best_choice is None:
            break
        out = apply_insertion(out, best_choice["insertion"], context)
        pending.remove(best_choice["customer"])
    return _finish(out, pending, context)


def opportunity_cost_insertion(solution, removed: list[str], context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Insert using OC benefit plus explicit postponement and day penalties."""

    out = solution.copy()
    pending = list(removed)
    eta = float(context.get("eta_oc", 0.5))
    theta = float(context.get("theta_postponement", 1000.0))
    phi = float(context.get("phi_delivery_day", 500.0))
    while pending:
        best = None
        for c in pending:
            limit = int(context.get("opportunity_candidate_limit", 3 if context.get("tune_light", False) else 5))
            positions = best_insertion_positions(out, c, context, limit=limit)
            for pos in positions:
                if context.get("tune_light", False):
                    # Screening can dung nhanh de xep hang config. Dung index nhe tranh quet future insertion qua sau.
                    feasibility_oc = compute_opportunity_index(c, out, pos["day"], context, pos["cost"]) * 1000.0
                else:
                    feasibility_oc = compute_feasibility_opportunity_cost(c, out, pos["day"], context)
                postponement_increment = compute_postponement_increment(c, pos["day"], context)
                delivery_day_increment = float(pos["day"] - min(context["days"]))
                adjusted = pos["cost"] - eta * feasibility_oc + theta * postponement_increment + phi * delivery_day_increment
                # OC chi giam chi phi khi co rui ro mat kha thi; giao tre bi phat rieng.
                if best is None or adjusted < best["adjusted"]:
                    best = {"customer": c, "insertion": pos, "adjusted": adjusted}
        if best is None:
            break
        out = apply_insertion(out, best["insertion"], context)
        pending.remove(best["customer"])
    return _finish(out, pending, context)


def early_day_repair(solution, removed: list[str], context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Reinsert removed customers into the earliest feasible day, using objective increase as tie-breaker."""

    out = solution.copy()
    pending = sorted(removed, key=lambda c: (context["first_available_day"].get(c, 99), c))
    while pending:
        best = None
        base_objective = evaluate_solution(out, context).objective_value
        attempts = 0
        max_attempts = int(context.get("early_day_repair_max_attempts", 30 if context.get("tune_light", False) else 10_000))
        for c in pending:
            positions = best_insertion_positions(out, c, context)
            if not positions:
                continue
            earliest_day = min(p["day"] for p in positions)
            for pos in [p for p in positions if p["day"] == earliest_day]:
                attempts += 1
                if attempts > max_attempts:
                    break
                candidate = apply_insertion(out, pos, context)
                objective_delta = evaluate_solution(candidate, context).objective_value - base_objective
                key = (pos["day"], objective_delta, pos["cost"])
                if best is None or key < best["key"]:
                    best = {"customer": c, "insertion": pos, "key": key}
            if attempts > max_attempts:
                break
        if best is None:
            break
        out = apply_insertion(out, best["insertion"], context)
        pending.remove(best["customer"])
    return _finish(out, pending, context)


def slack_aware_insertion(solution, removed: list[str], context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Insert while penalizing routes with very low slack."""

    out = solution.copy()
    pending = list(removed)
    while pending:
        best = None
        for c in pending:
            for pos in best_insertion_positions(out, c, context, limit=8):
                slack_penalty = 100.0 / (max(0.0, pos["min_slack"]) + 1.0)
                score = pos["cost"] + slack_penalty
                if best is None or score < best["score"]:
                    best = {"customer": c, "insertion": pos, "score": score}
        if best is None:
            break
        out = apply_insertion(out, best["insertion"], context)
        pending.remove(best["customer"])
    return _finish(out, pending, context)


BASE_REPAIR = {
    "cheapest_insertion": cheapest_insertion,
    "regret2_insertion": regret2_insertion,
}

OC_REPAIR = {
    **BASE_REPAIR,
    "regret3_insertion": regret3_insertion,
    "opportunity_cost_insertion": opportunity_cost_insertion,
    "early_day_repair": early_day_repair,
    "slack_aware_insertion": slack_aware_insertion,
}
