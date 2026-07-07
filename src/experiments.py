"""Top-level experiment orchestration."""

from __future__ import annotations

import logging
import random
from typing import Any

from .alns import run_alns
from .baselines import run_baselines
from .initial_solution import regret_insertion_initial_solution
from .reporting import export_all_schedules, export_daily_route_summary, export_results, export_schedule, export_undelivered, maybe_make_plots, save_histories


def run_all_experiments(context: dict[str, Any], out_dir: str, iterations: int, rng: random.Random, logger: logging.Logger, debug: bool = False):
    """Run baselines, ALNS-Base, ALNS-OC, and export all requested files."""

    solutions = run_baselines(context, logger)
    initial = regret_insertion_initial_solution(context, logger)

    base_solution, base_iter, base_ops = run_alns(initial, context, iterations, rng, variant="base", logger=logger, debug=debug)
    solutions["ALNS-Base"] = base_solution

    oc_solution, oc_iter, oc_ops = run_alns(initial, context, iterations, rng, variant="oc", logger=logger, debug=debug)
    solutions["ALNS-OC"] = oc_solution

    results_df = export_results(solutions, out_dir)
    best_method = results_df.sort_values(["objective", "undelivered_orders", "total_distance"]).iloc[0]["method"]
    best_solution = solutions[str(best_method)]
    export_all_schedules(solutions, context, out_dir)
    export_daily_route_summary(solutions, context, out_dir)
    export_schedule(str(best_method), best_solution, context, out_dir)
    export_undelivered(str(best_method), best_solution, context, out_dir)
    # Lưu lịch sử của biến thể đề xuất ALNS-OC vì đây là thuật toán chính.
    save_histories(oc_iter, oc_ops, out_dir)
    maybe_make_plots(results_df, oc_iter, out_dir)
    return solutions, results_df, str(best_method)
