"""Lightweight local search moves."""

from __future__ import annotations

from typing import Any

from .feasibility import evaluate_route, insertion_delta
from .objective import evaluate_solution


def improve(solution, context: dict[str, Any], max_moves: int = 30):
    """Apply first-improvement relocate and 2-opt moves."""

    out = solution.copy()
    if context.get("use_relocate_to_earlier_day", True):
        out = relocate_to_earlier_day(out, context, max_moves=max_moves)
    out = relocate_within_day(out, context, max_moves=max_moves)
    out = two_opt_within_day(out, context, max_moves=max_moves)
    return evaluate_solution(out, context)


def relocate_to_earlier_day(solution, context: dict[str, Any], max_moves: int = 30):
    """Move customers to earlier feasible days when the full objective improves."""

    out = evaluate_solution(solution, context)
    moves = 0
    improved = True
    while improved and moves < max_moves:
        improved = False
        assigned = []
        for day, route in out.routes.items():
            for customer in route.customers:
                first_day = context["first_available_day"].get(customer, day)
                if day > first_day:
                    assigned.append((day - first_day, day, customer))
        assigned.sort(reverse=True)

        for _lateness, current_day, customer in assigned:
            if moves >= max_moves:
                break
            base = out.copy()
            old_route = base.routes[current_day]
            old_customers = [c for c in old_route.customers if c != customer]
            new_old_route = evaluate_route(old_customers, current_day, context["depot_id"], context["tw_index"], context["travel_time"], context["distance"], context["service_times"], context["id_to_idx"], context.get("day_start", 0))
            if not new_old_route.feasible:
                continue
            base.routes[current_day] = new_old_route
            base.delivered.discard(customer)
            base.unassigned.add(customer)

            for target_day in [d for d in context["days"] if d < current_day and d >= context["first_available_day"].get(customer, 1)]:
                for position in range(len(base.routes[target_day].customers) + 1):
                    ins = insertion_delta(base, customer, target_day, position, context)
                    if ins is None:
                        continue
                    candidate = base.copy()
                    candidate.routes[target_day] = ins["route"]
                    candidate.delivered.add(customer)
                    candidate.unassigned.discard(customer)
                    candidate = evaluate_solution(candidate, context)
                    # Chap nhan chi khi objective that su giam, vi Big-M da gom postponement.
                    if candidate.objective_value + 1e-6 < out.objective_value:
                        out = candidate
                        moves += 1
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
    return out


def relocate_within_day(solution, context: dict[str, Any], max_moves: int = 30):
    """Move one customer to another position in the same day if distance improves."""

    out = solution.copy()
    moves = 0
    for day, route in list(out.routes.items()):
        improved = True
        while improved and moves < max_moves:
            improved = False
            base_distance = route.distance
            n = len(route.customers)
            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    customers = list(route.customers)
                    customer = customers.pop(i)
                    customers.insert(j, customer)
                    candidate = evaluate_route(customers, day, context["depot_id"], context["tw_index"], context["travel_time"], context["distance"], context["service_times"], context["id_to_idx"], context.get("day_start", 0))
                    if candidate.feasible and candidate.distance + 1e-6 < base_distance:
                        out.routes[day] = route = candidate
                        improved = True
                        moves += 1
                        break
                if improved:
                    break
    return out


def relocate_across_days(solution, context: dict[str, Any], max_moves: int = 20):
    """Move customers across days if both routes remain feasible."""

    # Hàm được giữ riêng để mở rộng; ALNS repair đã xử lý phần lớn di chuyển liên ngày.
    return solution


def swap_within_day(solution, context: dict[str, Any], max_moves: int = 20):
    """Swap two customers within a day if feasible and better."""

    return solution


def two_opt_within_day(solution, context: dict[str, Any], max_moves: int = 30):
    """Reverse a segment within a daily route if time windows remain feasible."""

    out = solution.copy()
    moves = 0
    for day, route in list(out.routes.items()):
        n = len(route.customers)
        if n < 4:
            continue
        for i in range(n - 2):
            if moves >= max_moves:
                break
            for j in range(i + 2, n):
                customers = list(route.customers)
                customers[i : j + 1] = reversed(customers[i : j + 1])
                candidate = evaluate_route(customers, day, context["depot_id"], context["tw_index"], context["travel_time"], context["distance"], context["service_times"], context["id_to_idx"], context.get("day_start", 0))
                if candidate.feasible and candidate.distance + 1e-6 < route.distance:
                    out.routes[day] = route = candidate
                    moves += 1
                    break
    return out
