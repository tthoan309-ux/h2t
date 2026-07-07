"""CSV and plot reporting helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import time

import pandas as pd

from .utils import minutes_to_time


RESULT_COLUMNS = [
    "method",
    "objective",
    "delivered_orders",
    "undelivered_orders",
    "completion_rate",
    "total_distance",
    "total_travel_time",
    "total_waiting_time",
    "postponement_penalty",
    "min_slack",
    "average_delivery_day",
    "runtime_seconds",
]


def export_results(solutions: dict[str, Any], out_dir: str | Path) -> pd.DataFrame:
    """Export method comparison metrics."""

    rows = []
    for method, solution in solutions.items():
        row = {"method": method}
        row.update(solution.metrics)
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in RESULT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[RESULT_COLUMNS]
    path = Path(out_dir) / "metrics" / "results_comparison.csv"
    _write_csv(df, path)
    return df


def export_schedule(method: str, solution, context: dict[str, Any], out_dir: str | Path, filename: str = "best_schedule.csv") -> pd.DataFrame:
    """Export a detailed visit-level schedule."""

    names = context["location_names"]
    rows = []
    for day, route in solution.routes.items():
        for visit in route.visits:
            rows.append(
                {
                    "method": method,
                    "day": day,
                    "sequence": visit.sequence,
                    "location_id": visit.customer_id,
                    "location_name": names.get(visit.customer_id, visit.customer_id),
                    "arrival_time": minutes_to_time(visit.arrival_time),
                    "service_start": minutes_to_time(visit.service_start),
                    "service_end": minutes_to_time(visit.service_end),
                    "window_start": minutes_to_time(visit.window_start),
                    "window_end": minutes_to_time(visit.window_end),
                    "waiting_time": visit.waiting_time,
                    "slack": visit.slack,
                    "distance_from_previous": visit.distance_from_previous,
                }
            )
        if route.customers:
            last_customer = route.customers[-1]
            id_to_idx = context["id_to_idx"]
            return_distance = float(context["distance"][id_to_idx[last_customer], id_to_idx[context["depot_id"]]])
            last_end = route.visits[-1].service_end if route.visits else 0.0
            return_arrival = last_end + float(context["travel_time"][id_to_idx[last_customer], id_to_idx[context["depot_id"]]])
            rows.append(
                {
                    "method": method,
                    "day": day,
                    "sequence": len(route.customers) + 1,
                    "location_id": context["depot_id"],
                    "location_name": names.get(context["depot_id"], context["depot_id"]),
                    "arrival_time": minutes_to_time(return_arrival),
                    "service_start": "",
                    "service_end": "",
                    "window_start": "",
                    "window_end": "",
                    "waiting_time": 0.0,
                    "slack": "",
                    "distance_from_previous": return_distance,
                }
            )
    df = pd.DataFrame(rows)
    path = Path(out_dir) / "schedules" / filename
    _write_csv(df, path)
    return df


def export_all_schedules(solutions: dict[str, Any], context: dict[str, Any], out_dir: str | Path) -> None:
    """Export one schedule CSV for every method."""

    filenames = {
        "Nearest Neighbor": "schedule_nearest_neighbor.csv",
        "Earliest Deadline First": "schedule_edf.csv",
        "Greedy Insertion": "schedule_greedy.csv",
        "ALNS-Base": "schedule_alns_base.csv",
        "ALNS-OC": "schedule_alns_oc.csv",
    }
    for method, solution in solutions.items():
        export_schedule(method, solution, context, out_dir, filenames.get(method, f"schedule_{_slug(method)}.csv"))


def export_daily_route_summary(solutions: dict[str, Any], context: dict[str, Any], out_dir: str | Path) -> pd.DataFrame:
    """Export daily route totals, including the return-to-depot distance."""

    rows = []
    for method, solution in solutions.items():
        for day, route in solution.routes.items():
            return_distance = 0.0
            if route.customers:
                id_to_idx = context["id_to_idx"]
                return_distance = float(context["distance"][id_to_idx[route.customers[-1]], id_to_idx[context["depot_id"]]])
            rows.append(
                {
                    "method": method,
                    "day": day,
                    "number_of_orders": len(route.customers),
                    "route_distance": route.distance,
                    "return_to_depot_distance": return_distance,
                    "total_waiting_time": route.waiting_time,
                    "min_slack": 0.0 if route.min_slack == float("inf") else route.min_slack,
                }
            )
    df = pd.DataFrame(rows)
    path = Path(out_dir) / "metrics" / "daily_route_summary.csv"
    _write_csv(df, path)
    return df


def _slug(method: str) -> str:
    """Return a lowercase filename-friendly method name."""

    return method.lower().replace(" ", "_").replace("-", "_")


def export_undelivered(method: str, solution, context: dict[str, Any], out_dir: str | Path) -> pd.DataFrame:
    """Export undelivered customers."""

    names = context["location_names"]
    rows = [{"method": method, "location_id": c, "location_name": names.get(c, c)} for c in sorted(solution.unassigned)]
    df = pd.DataFrame(rows)
    path = Path(out_dir) / "schedules" / "undelivered_orders.csv"
    _write_csv(df, path)
    return df


def save_histories(iteration_history: pd.DataFrame, operator_history: pd.DataFrame, out_dir: str | Path) -> None:
    """Save ALNS iteration and operator history CSV files."""

    metrics = Path(out_dir) / "metrics"
    _write_csv(iteration_history, metrics / "iteration_history.csv")
    _write_csv(operator_history, metrics / "operator_history.csv")


def _write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write a CSV, falling back to a timestamped file if the target is locked."""

    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")
        df.to_csv(fallback, index=False, encoding="utf-8-sig")
        print(f"Warning: could not overwrite locked file {path}; wrote {fallback} instead.")
        return fallback


def maybe_make_plots(results: pd.DataFrame, iteration_history: pd.DataFrame, out_dir: str | Path) -> None:
    """Create optional PNG plots when matplotlib is available."""

    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    metrics = Path(out_dir) / "metrics"
    if not iteration_history.empty:
        plt.figure(figsize=(8, 4))
        plt.plot(iteration_history["iteration"], iteration_history["best_objective"])
        plt.xlabel("Iteration")
        plt.ylabel("Best objective")
        plt.tight_layout()
        plt.savefig(metrics / "objective_progress.png", dpi=150)
        plt.close()
    if not results.empty:
        plt.figure(figsize=(8, 4))
        plt.bar(results["method"], results["delivered_orders"])
        plt.xticks(rotation=20, ha="right")
        plt.ylabel("Delivered orders")
        plt.tight_layout()
        plt.savefig(metrics / "method_comparison.png", dpi=150)
        plt.close()
