"""Central configuration for the delivery ALNS project."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectiveWeights:
    """Penalty weights for the lexicographic-like objective."""

    undelivered: float = 1_000_000.0
    postponed: float = 10_000.0
    distance: float = 10.0
    waiting: float = 1.0
    slack: float = 1.0


@dataclass(frozen=True)
class ALNSConfig:
    """Parameters used by the adaptive large neighborhood search."""

    speed_kmph: float = 50.0
    default_service_time: int = 5
    day_start: int = 0
    days: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
    t0: float = 1000.0
    cooling_rate: float = 0.995
    segment_length: int = 50
    reaction_factor: float = 0.2
    log_interval: int = 50
    local_search: bool = True
    large_penalty: float = 1_000_000.0
    random_min_remove: float = 0.05
    random_max_remove: float = 0.20
    eta_oc: float = 0.5
    theta_postponement: float = 1000.0
    phi_delivery_day: float = 500.0


OBJECTIVE_WEIGHTS = ObjectiveWeights()
ALNS_DEFAULTS = ALNSConfig()
