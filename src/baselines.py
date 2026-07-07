"""Baseline heuristics for comparison with ALNS."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from .feasibility import apply_insertion, best_insertion_positions, insertion_delta
from .initial_solution import empty_solution
from .objective import evaluate_solution


def greedy_insertion_baseline(context: dict[str, Any], logger: logging.Logger | None = None):
    """Build a schedule by cheapest feasible insertion only."""

    start = time.perf_counter()
    solution = empty_solution(context)
    pending = set(context["customer_ids"])
    while pending:
        best = None
        # Greedy baseline phải đủ nhanh để làm mốc so sánh. Ta xét trước nhóm khách
        # ít time window nhất, vì đây là nhóm dễ bị mất cơ hội giao nhất.
        ordered = sorted(
            pending,
            key=lambda c: (
                sum(len(context["tw_index"].get((c, d), [])) for d in context["days"]),
                context["first_available_day"].get(c, 99),
                c,
            ),
        )
        for c in ordered[: int(context.get("customer_scan_limit", len(ordered)))]:
            positions = best_insertion_positions(solution, c, context, limit=1)
            if positions and (best is None or positions[0]["cost"] < best["insertion"]["cost"]):
                best = {"customer": c, "insertion": positions[0]}
        if best is None:
            # Nếu shortlist không chèn được, thử một lượt đầy đủ trước khi kết luận còn lại không khả thi.
            for c in ordered:
                positions = best_insertion_positions(solution, c, context, limit=1)
                if positions and (best is None or positions[0]["cost"] < best["insertion"]["cost"]):
                    best = {"customer": c, "insertion": positions[0]}
            if best is None:
                break
        solution = apply_insertion(solution, best["insertion"], context)
        pending.remove(best["customer"])
    solution.unassigned |= pending
    return evaluate_solution(solution, context, runtime_seconds=time.perf_counter() - start)


def nearest_neighbor_baseline(context: dict[str, Any], logger: logging.Logger | None = None):
    """Construct each day by repeatedly adding the nearest feasible customer."""

    start = time.perf_counter()
    solution = empty_solution(context)
    pending = set(context["customer_ids"])
    for day in context["days"]:
        while pending:
            route = solution.routes[day]
            last = route.customers[-1] if route.customers else context["depot_id"]
            last_idx = context["id_to_idx"][last]
            candidates = []
            for c in pending:
                ins = insertion_delta(solution, c, day, len(route.customers), context)
                if ins:
                    candidates.append((float(context["distance"][last_idx, context["id_to_idx"][c]]), c, ins))
            if not candidates:
                break
            _dist, customer, insertion = min(candidates, key=lambda x: x[0])
            solution = apply_insertion(solution, insertion, context)
            pending.remove(customer)
    solution.unassigned |= pending
    return evaluate_solution(solution, context, runtime_seconds=time.perf_counter() - start)


def earliest_deadline_first_baseline(context: dict[str, Any], logger: logging.Logger | None = None):
    """Construct routes by choosing feasible customers with earliest window close."""

    start = time.perf_counter()
    solution = empty_solution(context)
    pending = set(context["customer_ids"])
    for day in context["days"]:
        while pending:
            candidates = []
            for c in pending:
                ins = insertion_delta(solution, c, day, len(solution.routes[day].customers), context)
                windows = context["tw_index"].get((c, day), [])
                if ins and windows:
                    candidates.append((min(end for _start, end in windows), c, ins))
            if not candidates:
                break
            _deadline, customer, insertion = min(candidates, key=lambda x: x[0])
            solution = apply_insertion(solution, insertion, context)
            pending.remove(customer)
    solution.unassigned |= pending
    return evaluate_solution(solution, context, runtime_seconds=time.perf_counter() - start)


def run_baselines(context: dict[str, Any], logger: logging.Logger | None = None) -> dict[str, Any]:
    """Run all required baseline methods."""

    methods = {
        "Nearest Neighbor": nearest_neighbor_baseline,
        "Earliest Deadline First": earliest_deadline_first_baseline,
        "Greedy Insertion": greedy_insertion_baseline,
    }
    results = {}
    for name, fn in methods.items():
        sol = fn(context, logger)
        if logger:
            logger.info("%s: delivered=%d/%d objective=%.2f distance=%.2f waiting=%.2f", name, sol.metrics["delivered_orders"], len(context["customer_ids"]), sol.objective_value, sol.metrics["total_distance"], sol.metrics["total_waiting_time"])
        results[name] = sol
    return results
