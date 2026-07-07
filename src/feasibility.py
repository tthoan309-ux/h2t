"""Route feasibility and insertion utilities."""

from __future__ import annotations

import logging
from typing import Any

from .models import Route, Solution, Visit


def build_time_window_index(time_windows_df) -> dict[tuple[str, int], list[tuple[int, int]]]:
    """Index time windows by (customer, day) for fast feasibility checks."""

    index: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for row in time_windows_df.itertuples(index=False):
        index.setdefault((str(row.location_id), int(row.day_of_week)), []).append((int(row.start_min), int(row.end_min)))
    for key in index:
        index[key].sort()
    return index


def evaluate_route(
    route_customers: list[str],
    day: int,
    depot_id: str,
    time_windows_by_customer_day: dict[tuple[str, int], list[tuple[int, int]]],
    travel_time,
    distance,
    service_times: dict[str, int],
    id_to_idx: dict[str, int],
    day_start: int = 0,
    debug: bool = False,
) -> Route:
    """Evaluate one ordered daily route against multiple time windows."""

    current_time = float(day_start)
    current = depot_id
    visits: list[Visit] = []
    total_distance = 0.0
    total_travel = 0.0
    total_waiting = 0.0
    min_slack = float("inf")

    for seq, customer in enumerate(route_customers, start=1):
        # Mỗi bước mô phỏng từ đầu tuyến, vì chèn một khách có thể làm trễ toàn bộ phần sau.
        i, j = id_to_idx[current], id_to_idx[customer]
        leg_distance = float(distance[i, j])
        leg_travel = float(travel_time[i, j])
        arrival = current_time + leg_travel
        windows = time_windows_by_customer_day.get((customer, day), [])
        chosen = None
        for start, end in windows:
            # Nếu đến sớm thì được chờ; nếu quá cuối cửa sổ thì thử cửa sổ sau.
            service_start = max(arrival, float(start))
            if service_start <= float(end):
                chosen = (start, end, service_start)
                break
        if chosen is None:
            reason = f"{customer} has no feasible window on day {day} after arrival {arrival:.1f}"
            return Route(day=day, customers=list(route_customers), visits=visits, distance=total_distance, travel_time=total_travel, waiting_time=total_waiting, min_slack=min_slack, feasible=False, infeasible_reason=reason if debug else "")
        start, end, service_start = chosen
        waiting = max(0.0, service_start - arrival)
        service_end = service_start + float(service_times.get(customer, 5))
        slack = float(end) - service_start
        visits.append(
            Visit(
                customer_id=customer,
                day=day,
                sequence=seq,
                arrival_time=arrival,
                service_start=service_start,
                service_end=service_end,
                window_start=float(start),
                window_end=float(end),
                waiting_time=waiting,
                slack=slack,
                distance_from_previous=leg_distance,
            )
        )
        total_distance += leg_distance
        total_travel += leg_travel
        total_waiting += waiting
        min_slack = min(min_slack, slack)
        current_time = service_end
        current = customer

    if route_customers:
        i, j = id_to_idx[current], id_to_idx[depot_id]
        total_distance += float(distance[i, j])
        total_travel += float(travel_time[i, j])
    return Route(day=day, customers=list(route_customers), visits=visits, distance=total_distance, travel_time=total_travel, waiting_time=total_waiting, min_slack=min_slack, feasible=True)


def rebuild_solution(solution: Solution, context: dict[str, Any], debug: bool = False) -> Solution:
    """Re-evaluate all routes and refresh delivered/unassigned sets."""

    out = solution.copy()
    delivered: set[str] = set()
    for day, route in out.routes.items():
        new_route = evaluate_route(route.customers, day, context["depot_id"], context["tw_index"], context["travel_time"], context["distance"], context["service_times"], context["id_to_idx"], context.get("day_start", 0), debug=debug)
        out.routes[day] = new_route
        if new_route.feasible:
            delivered.update(new_route.customers)
    out.delivered = delivered
    out.unassigned = set(context["customer_ids"]) - delivered
    return out


def insertion_delta(solution: Solution, customer: str, day: int, position: int, context: dict[str, Any]) -> dict | None:
    """Try one insertion and return its route-level delta if feasible."""

    route = solution.routes[day]
    new_customers = list(route.customers)
    new_customers.insert(position, customer)
    new_route = evaluate_route(new_customers, day, context["depot_id"], context["tw_index"], context["travel_time"], context["distance"], context["service_times"], context["id_to_idx"], context.get("day_start", 0))
    if not new_route.feasible:
        return None
    # Chi phí chèn tuyến là phần tăng khoảng cách/chờ; dùng nhanh cho repair/operator.
    old_distance = route.distance if route.feasible else 0.0
    old_waiting = route.waiting_time if route.feasible else 0.0
    delta = (new_route.distance - old_distance) * 10.0 + (new_route.waiting_time - old_waiting)
    return {"customer": customer, "day": day, "position": position, "route": new_route, "cost": float(delta), "min_slack": new_route.min_slack}


def best_insertion_positions(solution: Solution, customer: str, context: dict[str, Any], days: list[int] | None = None, limit: int | None = None) -> list[dict]:
    """Return feasible insertion positions sorted by insertion cost."""

    positions: list[dict] = []
    for day in (days or list(solution.routes.keys())):
        route = solution.routes[day]
        for pos in _candidate_positions(len(route.customers), context):
            item = insertion_delta(solution, customer, day, pos, context)
            if item is not None:
                positions.append(item)
    positions.sort(key=lambda x: (x["cost"], x["day"], x["position"]))
    return positions[:limit] if limit else positions


def _candidate_positions(route_length: int, context: dict[str, Any]) -> list[int]:
    """Return a bounded but well-spread set of insertion positions."""

    all_positions = list(range(route_length + 1))
    cap = int(context.get("max_positions_per_route", route_length + 1))
    if len(all_positions) <= cap:
        return all_positions
    # Với vài trăm khách, thử mọi vị trí làm greedy/ALNS quá chậm. Ta vẫn giữ đầu/cuối
    # và lấy mẫu đều trên tuyến để repair còn khả năng đổi cấu trúc tuyến.
    selected = {0, route_length}
    if cap > 2:
        step = max(1, route_length / (cap - 1))
        for k in range(cap):
            selected.add(int(round(k * step)))
    return sorted(p for p in selected if 0 <= p <= route_length)


def is_feasible_insertion(solution: Solution, customer: str, day: int, position: int, context: dict[str, Any]) -> bool:
    """Return whether inserting a customer at one position keeps the route feasible."""

    return insertion_delta(solution, customer, day, position, context) is not None


def apply_insertion(solution: Solution, insertion: dict, context: dict[str, Any]) -> Solution:
    """Apply a feasible insertion and refresh assignment sets."""

    out = solution.copy()
    day = insertion["day"]
    out.routes[day] = insertion["route"]
    out.delivered.add(insertion["customer"])
    out.unassigned.discard(insertion["customer"])
    return out


def remove_customers(solution: Solution, removed: list[str], context: dict[str, Any], logger: logging.Logger | None = None) -> Solution:
    """Remove customers from routes and re-evaluate affected days."""

    out = solution.copy()
    removed_set = set(removed)
    for day, route in out.routes.items():
        if removed_set.intersection(route.customers):
            route.customers = [c for c in route.customers if c not in removed_set]
            out.routes[day] = evaluate_route(route.customers, day, context["depot_id"], context["tw_index"], context["travel_time"], context["distance"], context["service_times"], context["id_to_idx"], context.get("day_start", 0))
    out.delivered -= removed_set
    out.unassigned |= removed_set
    if logger:
        logger.debug("Removed customers: %s", removed)
    return out
