"""Dataclasses that represent the weekly delivery schedule."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Customer:
    """A delivery customer or depot point."""

    id: str
    name: str
    x: float
    y: float
    demand: float = 0.0
    service_time: int = 5


@dataclass
class TimeWindow:
    """A receiving time window for one customer on one day."""

    customer_id: str
    day: int
    start_min: int
    end_min: int


@dataclass
class Visit:
    """A scheduled visit with timing details after route evaluation."""

    customer_id: str
    day: int
    sequence: int
    arrival_time: float
    service_start: float
    service_end: float
    window_start: float
    window_end: float
    waiting_time: float
    slack: float
    distance_from_previous: float = 0.0


@dataclass
class Route:
    """One daily route starting at the depot and returning to the depot."""

    day: int
    customers: list[str] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)
    distance: float = 0.0
    travel_time: float = 0.0
    waiting_time: float = 0.0
    min_slack: float = float("inf")
    feasible: bool = True
    infeasible_reason: str = ""

    def copy(self) -> "Route":
        """Return a shallow copy with copied customer and visit lists."""

        return Route(
            day=self.day,
            customers=list(self.customers),
            visits=list(self.visits),
            distance=self.distance,
            travel_time=self.travel_time,
            waiting_time=self.waiting_time,
            min_slack=self.min_slack,
            feasible=self.feasible,
            infeasible_reason=self.infeasible_reason,
        )


@dataclass
class Solution:
    """A full weekly schedule, not a single-day route."""

    routes: dict[int, Route]
    unassigned: set[str] = field(default_factory=set)
    delivered: set[str] = field(default_factory=set)
    objective_value: float = float("inf")
    metrics: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "Solution":
        """Deep enough copy for ALNS operators."""

        return Solution(
            routes={day: route.copy() for day, route in self.routes.items()},
            unassigned=set(self.unassigned),
            delivered=set(self.delivered),
            objective_value=self.objective_value,
            metrics=dict(self.metrics),
        )

    def assigned_day(self, customer_id: str) -> int | None:
        """Return the delivery day of a customer if it is scheduled."""

        for day, route in self.routes.items():
            if customer_id in route.customers:
                return day
        return None
