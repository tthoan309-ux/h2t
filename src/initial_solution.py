"""Initial solution construction."""

from __future__ import annotations

import logging
from typing import Any

from .feasibility import apply_insertion, best_insertion_positions
from .models import Route, Solution
from .objective import evaluate_solution
from .opportunity_cost import compute_opportunity_cost


def empty_solution(context: dict[str, Any]) -> Solution:
    """Create an empty weekly schedule."""

    return Solution(routes={day: Route(day=day) for day in context["days"]}, unassigned=set(context["customer_ids"]))


def regret_insertion_initial_solution(context: dict[str, Any], logger: logging.Logger | None = None) -> Solution:
    """Build a feasible initial solution using regret insertion and opportunity cost."""

    logger = logger or logging.getLogger("delivery_alns")
    solution = empty_solution(context)
    remaining = set(context["customer_ids"])
    inserted = 0

    while remaining:
        best_choice = None
        impossible: list[str] = []
        # Không quét toàn bộ 300 khách ở mọi vòng vì chi phí rất cao. Khách ít cửa sổ
        # còn lại được xét trước vì chúng dễ trở thành undelivered nếu chậm tay.
        ordered = sorted(
            remaining,
            key=lambda c: (
                sum(len(context["tw_index"].get((c, d), [])) for d in context["days"]),
                context["first_available_day"].get(c, 99),
                c,
            ),
        )
        scan_limit = int(context.get("customer_scan_limit", len(ordered)))
        for customer in ordered[:scan_limit]:
            positions = best_insertion_positions(solution, customer, context, limit=3)
            if not positions:
                impossible.append(customer)
                continue
            best = positions[0]
            second = positions[1]["cost"] if len(positions) > 1 else context["large_penalty"]
            third = positions[2]["cost"] if len(positions) > 2 else second
            regret2 = second - best["cost"]
            regret3 = third - best["cost"]
            oc = compute_opportunity_cost(customer, solution, best["day"], context)
            # Ưu tiên khách có ít lựa chọn tốt; trừ chi phí chèn để không tạo tuyến quá vòng vèo.
            priority = 1.0 * regret2 + 0.3 * regret3 + 0.5 * oc - 0.1 * best["cost"]
            if best_choice is None or priority > best_choice["priority"]:
                best_choice = {"customer": customer, "insertion": best, "priority": priority}
        if best_choice is None:
            break
        customer = best_choice["customer"]
        solution = apply_insertion(solution, best_choice["insertion"], context)
        remaining.remove(customer)
        inserted += 1
        if len(impossible) >= scan_limit and best_choice is None:
            for customer in impossible:
                if customer in remaining:
                    remaining.remove(customer)
                    solution.unassigned.add(customer)
        if inserted % 25 == 0:
            logger.debug("Initial insertion progress: inserted=%d remaining=%d", inserted, len(remaining))

    solution.unassigned |= remaining
    solution = evaluate_solution(solution, context)
    logger.info(
        "Initial solution: inserted=%d unassigned=%d objective=%.2f distance=%.2f waiting=%.2f",
        len(solution.delivered),
        len(solution.unassigned),
        solution.objective_value,
        solution.metrics["total_distance"],
        solution.metrics["total_waiting_time"],
    )
    return solution
