"""Adaptive Large Neighborhood Search main loop."""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Any

import pandas as pd

from config import ALNS_DEFAULTS
from .destroy_operators import BASE_DESTROY, OC_DESTROY
from .local_search import improve
from .objective import evaluate_solution
from .repair_operators import BASE_REPAIR, OC_REPAIR
from .utils import roulette_choice


def run_alns(
    initial_solution,
    context: dict[str, Any],
    iterations: int,
    rng: random.Random,
    variant: str = "oc",
    logger: logging.Logger | None = None,
    debug: bool = False,
):
    """Run ALNS with adaptive operator weights and simulated annealing."""

    logger = logger or logging.getLogger("delivery_alns")
    destroy_ops = OC_DESTROY if variant == "oc" else BASE_DESTROY
    repair_ops = OC_REPAIR if variant == "oc" else BASE_REPAIR
    if variant == "oc":
        repair_ops = dict(repair_ops)
        if not context.get("use_early_day_repair", True):
            repair_ops.pop("early_day_repair", None)
        if not context.get("use_slack_penalty", True):
            repair_ops.pop("slack_aware_insertion", None)
        if context.get("tune_light", False):
            # Screening chi can xep hang nhanh config tiem nang, nen bo operator rat nang.
            repair_ops.pop("regret3_insertion", None)
    destroy_weights = {name: 1.0 for name in destroy_ops}
    repair_weights = {name: 1.0 for name in repair_ops}
    d_score = {name: 0.0 for name in destroy_ops}
    r_score = {name: 0.0 for name in repair_ops}
    d_use = {name: 0 for name in destroy_ops}
    r_use = {name: 0 for name in repair_ops}
    current = evaluate_solution(initial_solution, context)
    best = current.copy()
    temperature = float(context.get("temperature_initial", ALNS_DEFAULTS.t0))
    cooling_rate = float(context.get("cooling_rate", ALNS_DEFAULTS.cooling_rate))
    start = time.perf_counter()
    iteration_rows = []
    operator_rows = []
    stop_reason = "success"
    best_checkpoint_objective = best.objective_value
    last_significant_improvement = 0
    early_stop = bool(context.get("early_stop", False))
    patience = int(context.get("patience", 150))
    min_improvement = float(context.get("min_improvement", 1000.0))
    checkpoint_interval = int(context.get("checkpoint_interval", 0))
    checkpoint_callback = context.get("checkpoint_callback")
    prune_after = int(context.get("prune_after_iterations", 0))
    prune_reference = context.get("prune_reference_objective")
    prune_gap = float(context.get("prune_gap", 0.15))

    for iteration in range(1, iterations + 1):
        d_name = roulette_choice(destroy_weights, rng)
        r_name = roulette_choice(repair_weights, rng)
        delivered_count = max(1, len(current.delivered))
        q = max(1, int(rng.uniform(context["random_min_remove"], context["random_max_remove"]) * delivered_count))
        q = min(q, int(context.get("max_removed_per_iteration", q)))

        partial, removed = destroy_ops[d_name](current, q, context, rng, None)
        candidate = repair_ops[r_name](partial, removed, context, rng, None)
        candidate = evaluate_solution(candidate, context, runtime_seconds=time.perf_counter() - start)
        if context.get("local_search", True) and iteration % 5 == 0:
            candidate = improve(candidate, context, max_moves=10 if debug else 20)

        delta = candidate.objective_value - current.objective_value
        accepted = delta < 0
        if not accepted:
            # Big-M objective can make deltas huge; scale by delivered count to keep SA useful.
            scaled_delta = delta / max(1.0, len(context["customer_ids"]))
            accepted = rng.random() < math.exp(-scaled_delta / max(1e-9, temperature))

        reward = 0
        if candidate.objective_value < best.objective_value:
            best = candidate.copy()
            current = candidate
            accepted = True
            reward = 30
            if best_checkpoint_objective - best.objective_value >= min_improvement:
                best_checkpoint_objective = best.objective_value
                last_significant_improvement = iteration
        elif delta < 0:
            current = candidate
            reward = 10
        elif accepted:
            current = candidate
            reward = 5

        d_score[d_name] += reward
        r_score[r_name] += reward
        d_use[d_name] += 1
        r_use[r_name] += 1
        temperature *= cooling_rate

        row = {
            "iteration": iteration,
            "current_objective": current.objective_value,
            "best_objective": best.objective_value,
            "delivered_orders": best.metrics.get("delivered_orders", 0),
            "undelivered_orders": best.metrics.get("undelivered_orders", 0),
            "total_distance": best.metrics.get("total_distance", 0.0),
            "total_waiting_time": best.metrics.get("total_waiting_time", 0.0),
            "destroy_operator": d_name,
            "repair_operator": r_name,
            "accepted": bool(accepted),
            "temperature": temperature,
        }
        iteration_rows.append(row)

        if iteration % ALNS_DEFAULTS.segment_length == 0:
            _update_weights(destroy_weights, d_score, d_use, context)
            _update_weights(repair_weights, r_score, r_use, context)
            for name in destroy_weights:
                operator_rows.append({"iteration": iteration, "type": "destroy", "operator": name, "weight": destroy_weights[name], "score": d_score[name], "usage": d_use[name]})
                d_score[name] = 0.0
                d_use[name] = 0
            for name in repair_weights:
                operator_rows.append({"iteration": iteration, "type": "repair", "operator": name, "weight": repair_weights[name], "score": r_score[name], "usage": r_use[name]})
                r_score[name] = 0.0
                r_use[name] = 0

        if iteration == 1 or iteration % context["log_interval"] == 0:
            logger.info(
                "%s iter=%d current=%.2f best=%.2f delivered=%s undelivered=%s dist=%.2f wait=%.2f d=%s r=%s accepted=%s T=%.2f",
                "ALNS-OC" if variant == "oc" else "ALNS-Base",
                iteration,
                current.objective_value,
                best.objective_value,
                best.metrics.get("delivered_orders"),
                best.metrics.get("undelivered_orders"),
                best.metrics.get("total_distance"),
                best.metrics.get("total_waiting_time"),
                d_name,
                r_name,
                accepted,
                temperature,
            )

        if checkpoint_interval > 0 and checkpoint_callback and iteration % checkpoint_interval == 0:
            checkpoint_callback(iteration, best, "running")

        # Pruning cat nhanh config kem trong tuning. Feasibility van dung exact, chi dung de dung som run kem.
        if prune_after > 0 and iteration >= prune_after:
            if best.metrics.get("delivered_orders", 0) < len(context["customer_ids"]):
                stop_reason = "pruned"
                break
            if prune_reference is not None and best.objective_value > float(prune_reference) * (1.0 + prune_gap):
                stop_reason = "pruned"
                break

        # Early stopping tiet kiem thoi gian khi objective khong con cai thien dang ke.
        if early_stop and iteration - last_significant_improvement >= patience:
            stop_reason = "early_stopped"
            break

    best = evaluate_solution(best, context, runtime_seconds=time.perf_counter() - start)
    best.metrics["run_status"] = stop_reason
    best.metrics["completed_iterations"] = iteration_rows[-1]["iteration"] if iteration_rows else 0
    if checkpoint_callback:
        checkpoint_callback(best.metrics["completed_iterations"], best, stop_reason)
    return best, pd.DataFrame(iteration_rows), pd.DataFrame(operator_rows)


def _update_weights(weights: dict[str, float], scores: dict[str, float], uses: dict[str, int], context: dict[str, Any]) -> None:
    """Update adaptive operator weights after a segment."""

    rho = float(context.get("rho_operator_learning", ALNS_DEFAULTS.reaction_factor))
    for name in weights:
        if uses[name] > 0:
            average = scores[name] / uses[name]
            weights[name] = (1.0 - rho) * weights[name] + rho * max(0.1, average)
