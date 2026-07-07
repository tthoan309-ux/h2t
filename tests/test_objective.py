from src.models import Route, Solution
from src.objective import evaluate_solution


def test_undelivered_penalty_dominates_distance():
    context = {"customer_ids": ["C1", "C2"], "first_available_day": {"C1": 1, "C2": 1}}
    worse = Solution(routes={1: Route(day=1, customers=["C1"], distance=0)}, delivered={"C1"}, unassigned={"C2"})
    better = Solution(routes={1: Route(day=1, customers=["C1", "C2"], distance=10000)}, delivered={"C1", "C2"}, unassigned=set())
    worse = evaluate_solution(worse, context)
    better = evaluate_solution(better, context)
    assert better.objective_value < worse.objective_value


def test_objective_decreases_when_customer_delivered():
    context = {"customer_ids": ["C1"], "first_available_day": {"C1": 1}}
    undelivered = Solution(routes={1: Route(day=1)}, delivered=set(), unassigned={"C1"})
    delivered = Solution(routes={1: Route(day=1, customers=["C1"], distance=1)}, delivered={"C1"}, unassigned=set())
    assert evaluate_solution(delivered, context).objective_value < evaluate_solution(undelivered, context).objective_value
