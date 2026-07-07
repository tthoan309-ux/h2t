"""Destroy operators for ALNS."""

from __future__ import annotations

import logging
import random
from typing import Any

from .feasibility import remove_customers
from .opportunity_cost import compute_opportunity_cost


def _sample(items: list[str], q: int, rng: random.Random) -> list[str]:
    """Sample at most q items."""

    if not items:
        return []
    return rng.sample(items, min(q, len(items)))


def random_removal(solution, q: int, context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Randomly remove delivered customers to diversify the search."""

    removed = _sample(list(solution.delivered), q, rng)
    if logger:
        logger.debug("random_removal removed=%s", removed)
    return remove_customers(solution, removed, context, logger), removed


def worst_removal(solution, q: int, context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Remove customers with high distance/wait/slack contribution."""

    scores = []
    for day, route in solution.routes.items():
        customers = route.customers
        for idx, customer in enumerate(customers):
            prev_id = context["depot_id"] if idx == 0 else customers[idx - 1]
            next_id = context["depot_id"] if idx == len(customers) - 1 else customers[idx + 1]
            id_to_idx = context["id_to_idx"]
            dist = context["distance"]
            saving = dist[id_to_idx[prev_id], id_to_idx[customer]] + dist[id_to_idx[customer], id_to_idx[next_id]] - dist[id_to_idx[prev_id], id_to_idx[next_id]]
            visit = next((v for v in route.visits if v.customer_id == customer), None)
            risk = 1.0 / (max(0.0, visit.slack) + 1.0) if visit else 0.0
            scores.append((float(saving) + 10.0 * risk, customer))
    scores.sort(reverse=True)
    removed = [c for _score, c in scores[:q]]
    if logger:
        logger.debug("worst_removal removed=%s", removed)
    return remove_customers(solution, removed, context, logger), removed


def related_removal(solution, q: int, context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Remove a spatially and temporally related customer cluster."""

    delivered = list(solution.delivered)
    if not delivered:
        return solution.copy(), []
    seed = rng.choice(delivered)
    seed_day = solution.assigned_day(seed) or 1
    id_to_idx = context["id_to_idx"]
    scores = []
    for customer in delivered:
        if customer == seed:
            continue
        day = solution.assigned_day(customer) or seed_day
        spatial = float(context["distance"][id_to_idx[seed], id_to_idx[customer]])
        temporal = abs(day - seed_day) * 20.0
        windows_seed = context["tw_index"].get((seed, seed_day), [(0, 1440)])
        windows_c = context["tw_index"].get((customer, day), [(0, 1440)])
        tw_gap = min(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in windows_seed for b in windows_c) / 60.0
        scores.append((spatial + temporal + tw_gap, customer))
    scores.sort()
    removed = [seed] + [c for _score, c in scores[: max(0, q - 1)]]
    if logger:
        logger.debug("related_removal seed=%s removed=%s", seed, removed)
    return remove_customers(solution, removed, context, logger), removed


def time_window_conflict_removal(solution, q: int, context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Remove customers in crowded overlapping time windows."""

    scores = []
    for day, route in solution.routes.items():
        for visit in route.visits:
            length = max(1.0, visit.window_end - visit.window_start)
            overlaps = sum(
                1
                for other in route.visits
                if other.customer_id != visit.customer_id
                and max(visit.window_start, other.window_start) < min(visit.window_end, other.window_end)
            )
            scores.append((overlaps / length, visit.customer_id))
    scores.sort(reverse=True)
    removed = [c for _score, c in scores[:q]]
    if logger:
        logger.debug("time_window_conflict_removal removed=%s", removed)
    return remove_customers(solution, removed, context, logger), removed


def day_removal(solution, q: int, context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Remove customers from the most problematic day to rebalance the week."""

    candidates = [r for r in solution.routes.values() if r.customers]
    if not candidates:
        return solution.copy(), []
    # Điểm ngày: nhiều chờ + xa + slack thấp, thể hiện ngày đang bị căng.
    day_route = max(candidates, key=lambda r: r.waiting_time + 0.1 * r.distance + (1000.0 / (max(0.0, r.min_slack) + 1.0)))
    removed = _sample(day_route.customers, q, rng)
    if logger:
        logger.debug("day_removal day=%s removed=%s", day_route.day, removed)
    return remove_customers(solution, removed, context, logger), removed


def low_opportunity_removal(solution, q: int, context: dict[str, Any], rng: random.Random, logger: logging.Logger | None = None):
    """Remove flexible customers with low postponement opportunity cost."""

    scores = []
    for customer in solution.delivered:
        day = solution.assigned_day(customer) or 1
        scores.append((compute_opportunity_cost(customer, solution, day, context), customer))
    scores.sort()
    removed = [c for _score, c in scores[:q]]
    if logger:
        logger.debug("low_opportunity_removal removed=%s", removed)
    return remove_customers(solution, removed, context, logger), removed


BASE_DESTROY = {
    "random_removal": random_removal,
    "worst_removal": worst_removal,
    "related_removal": related_removal,
}

OC_DESTROY = {
    **BASE_DESTROY,
    "time_window_conflict_removal": time_window_conflict_removal,
    "day_removal": day_removal,
    "low_opportunity_removal": low_opportunity_removal,
}
