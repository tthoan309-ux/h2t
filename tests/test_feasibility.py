import numpy as np

from src.feasibility import evaluate_route


def _ctx():
    ids = {"DEPOT": 0, "C1": 1, "C2": 2}
    distance = np.array([[0, 10, 20], [10, 0, 5], [20, 5, 0]], dtype=float)
    travel = distance * 1.2
    service = {"DEPOT": 0, "C1": 5, "C2": 5}
    return ids, distance, travel, service


def test_route_with_valid_time_window_is_feasible():
    ids, distance, travel, service = _ctx()
    tw = {("C1", 1): [(0, 100)]}
    route = evaluate_route(["C1"], 1, "DEPOT", tw, travel, distance, service, ids)
    assert route.feasible


def test_route_outside_all_windows_is_infeasible():
    ids, distance, travel, service = _ctx()
    tw = {("C1", 1): [(0, 5)]}
    route = evaluate_route(["C1"], 1, "DEPOT", tw, travel, distance, service, ids)
    assert not route.feasible


def test_multiple_windows_can_use_later_window():
    ids, distance, travel, service = _ctx()
    tw = {("C1", 1): [(0, 5), (20, 40)]}
    route = evaluate_route(["C1"], 1, "DEPOT", tw, travel, distance, service, ids)
    assert route.feasible
    assert route.visits[0].service_start == 20
