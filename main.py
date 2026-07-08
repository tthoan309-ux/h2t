"""Command-line entry point for the delivery ALNS project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from config import ALNS_DEFAULTS
from src.alns import run_alns
from src.baselines import run_baselines
from src.data_loader import load_data
from src.distance import build_matrices
from src.experiments import run_all_experiments
from src.feasibility import build_time_window_index
from src.initial_solution import regret_insertion_initial_solution
from src.parameter_grid import count_parameter_space, default_search_strategy, get_parameter_grid
from src.reporting import maybe_make_plots
from src.tuning import run_grid_search
from src.utils import ensure_dirs, set_seed, setup_logging


def build_context(data: dict, matrices: dict, debug: bool = False) -> dict:
    """Build the shared context dictionary passed to all modules."""

    locations = data["locations_df"]
    windows = data["time_windows_df"]
    service_times = dict(zip(locations["location_id"].astype(str), locations["service_time"].astype(int)))
    first_available_day = windows.groupby("location_id")["day_of_week"].min().astype(int).to_dict()
    location_names = dict(zip(locations["location_id"].astype(str), locations["location_name"].astype(str)))
    return {
        "locations_df": locations,
        "time_windows_df": windows,
        "depot_id": data["depot_id"],
        "customer_ids": data["customer_ids"],
        "tw_index": build_time_window_index(windows),
        "service_times": service_times,
        "first_available_day": first_available_day,
        "location_names": location_names,
        "days": list(ALNS_DEFAULTS.days),
        "day_start": ALNS_DEFAULTS.day_start,
        "large_penalty": ALNS_DEFAULTS.large_penalty,
        "eta_oc": ALNS_DEFAULTS.eta_oc,
        "theta_postponement": ALNS_DEFAULTS.theta_postponement,
        "phi_delivery_day": ALNS_DEFAULTS.phi_delivery_day,
        "rho_operator_learning": ALNS_DEFAULTS.reaction_factor,
        "temperature_initial": ALNS_DEFAULTS.t0,
        "cooling_rate": ALNS_DEFAULTS.cooling_rate,
        "use_slack_penalty": True,
        "use_early_day_repair": True,
        "use_relocate_to_earlier_day": True,
        "distance": matrices["distance"],
        "travel_time": matrices["travel_time"],
        "id_to_idx": matrices["id_to_idx"],
        "random_min_remove": ALNS_DEFAULTS.random_min_remove,
        "random_max_remove": ALNS_DEFAULTS.random_max_remove,
        "max_removed_per_iteration": 10 if debug else 35,
        "log_interval": 25 if debug else ALNS_DEFAULTS.log_interval,
        "local_search": False if debug else ALNS_DEFAULTS.local_search,
        "max_positions_per_route": 8 if debug else 16,
        "customer_scan_limit": 60 if debug else 120,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Multi-day delivery scheduling with ALNS and opportunity cost.")
    parser.add_argument("--data", required=True, help="Path to Data_B.zip or a folder containing the CSV files.")
    parser.add_argument("--out", default="outputs", help="Output directory.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--iterations", type=int, help="ALNS iterations per variant.")
    parser.add_argument("--debug", action="store_true", help="Use more verbose logging.")
    parser.add_argument("--tune", action="store_true", help="Enable ALNS-OC parameter tuning mode.")
    parser.add_argument("--tune-mode", choices=["quick", "full", "custom"], default="quick", help="Parameter grid size/source.")
    parser.add_argument("--search-strategy", choices=["grid", "random", "latin"], help="Tuning search strategy. Defaults to random for full mode, grid otherwise.")
    parser.add_argument("--n-configs", type=int, help="Number of sampled configs for random/latin search.")
    parser.add_argument("--grid-file", help="JSON grid file for --tune-mode custom.")
    parser.add_argument("--tune-seeds", default="42", help="Comma-separated seeds for tuning, e.g. 1,2,3.")
    parser.add_argument("--max-configs", type=int, help="Optional maximum number of tuning configs.")
    parser.add_argument("--resume", action="store_true", help="Skip successful config/seed rows already in tuning raw CSV.")
    parser.add_argument("--parallel", type=int, help="Optional number of parallel tuning workers.")
    parser.add_argument("--tuning-stage", choices=["screening", "focused", "validation"], help="Successive-halving tuning stage preset.")
    parser.add_argument("--early-stop", dest="early_stop", action="store_true", help="Enable early stopping inside tuning runs.")
    parser.add_argument("--no-early-stop", dest="early_stop", action="store_false", help="Disable early stopping inside tuning runs.")
    parser.set_defaults(early_stop=None)
    parser.add_argument("--patience", type=int, help="Early-stop patience in ALNS iterations.")
    parser.add_argument("--min-improvement", type=float, help="Minimum objective improvement needed to reset patience.")
    parser.add_argument("--tune-light", action="store_true", help="Use lighter operators/settings for fast screening.")
    parser.add_argument("--use-best-config", help="Path to outputs/tuning/best_config.json for final tuned runs.")
    parser.add_argument("--seeds", help="Comma-separated seeds for final repeated tuned runs.")
    return parser.parse_args()


def main() -> None:
    """Run the full experiment workflow."""

    args = parse_args()
    _apply_stage_defaults(args)
    if args.iterations is None:
        args.iterations = 5000
    if args.debug and args.iterations > 300:
        args.iterations = 300
    ensure_dirs(args.out)
    logger = setup_logging(args.out, args.debug)
    rng = set_seed(args.seed)
    logger.info("Run started: data=%s out=%s seed=%d iterations=%d debug=%s", args.data, args.out, args.seed, args.iterations, args.debug)

    data = load_data(args.data, ALNS_DEFAULTS.default_service_time, logger)
    matrices = build_matrices(data["locations_df"], ALNS_DEFAULTS.speed_kmph)
    context = build_context(data, matrices, args.debug)
    if args.tune:
        strategy = default_search_strategy(args.tune_mode, args.search_strategy)
        # --n-configs lay mau tren toan bo khong gian, tot hon --max-configs vi --max-configs chi cat N config dau sau khi sort.
        if strategy in {"random", "latin"} and args.n_configs is None:
            args.n_configs = 50 if args.tune_mode == "full" else 10
            logger.warning("--n-configs not provided for %s search; using %d", strategy, args.n_configs)
        space_size = count_parameter_space(args.tune_mode, args.grid_file)
        grid = get_parameter_grid(args.tune_mode, args.grid_file, strategy, args.n_configs, args.seed)
        seeds = _parse_seeds(args.tune_seeds)
        planned_configs = min(len(grid), args.max_configs or len(grid))
        total_jobs = planned_configs * len(seeds)
        logger.info("Tuning search: mode=%s strategy=%s parameter_space=%d selected_configs=%d seeds=%d jobs=%d", args.tune_mode, strategy, space_size, planned_configs, len(seeds), total_jobs)
        if total_jobs > 1000:
            warning = f"Warning: this tuning run contains {total_jobs} jobs. Consider using --n-configs or --max-configs."
            print(warning)
            logger.warning(warning)
        summary = run_grid_search(
            context,
            args.out,
            {},
            grid,
            seeds,
            args.iterations,
            resume=args.resume,
            max_configs=args.max_configs,
            parallel=args.parallel,
            logger=logger,
            early_stop=True if args.early_stop is None else args.early_stop,
            patience=args.patience if args.patience is not None else 150,
            min_improvement=args.min_improvement if args.min_improvement is not None else 1000.0,
            tune_light=args.tune_light,
        )
        best = summary.iloc[0]
        print("\nTuning summary:")
        print(f"- configurations tested: {summary['config_id'].nunique()}")
        print(f"- successful runs: {int(summary['n_seeds'].sum())}")
        print(f"- best config_id: {best.config_id}")
        print(f"- best mean objective: {best.mean_objective:.2f}")
        print(f"- best mean completion rate: {best.mean_completion_rate:.4f}")
        print(f"- best mean postponement penalty: {best.mean_postponement_penalty:.2f}")
        print(f"- best mean total distance: {best.mean_total_distance:.2f}")
        return

    if args.use_best_config:
        seeds = _parse_seeds(args.seeds) if args.seeds else [args.seed]
        _run_final_tuned_comparison(context, args.out, args.use_best_config, args.iterations, seeds, logger, args.debug)
        return

    solutions, results, best_method = run_all_experiments(context, args.out, args.iterations, rng, logger, args.debug)

    print("\nMethod comparison:")
    total = len(context["customer_ids"])
    for row in results.itertuples(index=False):
        print(f"- {row.method}: delivered {int(row.delivered_orders)}/{total}, distance {row.total_distance:.2f}, waiting {row.total_waiting_time:.2f}, objective {row.objective:.2f}")
    best_completion = results.sort_values(["completion_rate", "objective"], ascending=[False, True]).iloc[0]["method"]
    print(f"\nBest method by completion rate: {best_completion}")
    print(f"Best method by objective: {best_method}")
    print(f"Path to best_schedule.csv: {Path(args.out) / 'schedules' / 'best_schedule.csv'}")
    print(f"Path to results_comparison.csv: {Path(args.out) / 'metrics' / 'results_comparison.csv'}")


def _parse_seeds(text: str) -> list[int]:
    """Parse comma-separated seed text."""

    return [int(part.strip()) for part in text.split(",") if part.strip()]


def _apply_stage_defaults(args: argparse.Namespace) -> None:
    """Apply successive-halving defaults before running tuning."""

    if not args.tune or not args.tuning_stage:
        return
    # Successive halving: rong truoc, sau do moi tang seed/iterations cho vung tham so co trien vong.
    if args.tuning_stage == "screening":
        args.n_configs = args.n_configs or 20
        args.tune_seeds = args.tune_seeds if args.tune_seeds != "42" else "1"
        args.iterations = args.iterations or 200
        args.tune_light = True if not args.tune_light else args.tune_light
    elif args.tuning_stage == "focused":
        args.n_configs = args.n_configs or 10
        args.tune_seeds = args.tune_seeds if args.tune_seeds != "42" else "1,2,3"
        args.iterations = args.iterations or 800
    elif args.tuning_stage == "validation":
        args.n_configs = args.n_configs or 1
        args.tune_seeds = args.tune_seeds if args.tune_seeds != "42" else "1,2,3,4,5"
        args.iterations = args.iterations or 3000


def _apply_tuned_config(context: dict, config: dict) -> dict:
    """Return a context updated by a tuned config JSON."""

    out = dict(context)
    mapping = {
        "eta_oc": "eta_oc",
        "theta_postponement": "theta_postponement",
        "phi_delivery_day": "phi_delivery_day",
        "rho_operator_learning": "rho_operator_learning",
        "temperature_initial": "temperature_initial",
        "cooling_rate": "cooling_rate",
        "removal_fraction_min": "random_min_remove",
        "removal_fraction_max": "random_max_remove",
        "use_slack_penalty": "use_slack_penalty",
        "use_early_day_repair": "use_early_day_repair",
        "use_relocate_to_earlier_day": "use_relocate_to_earlier_day",
    }
    for src, dst in mapping.items():
        if src in config:
            out[dst] = config[src]
    return out


def _run_final_tuned_comparison(context: dict, out_dir: str, best_config_path: str, iterations: int, seeds: list[int], logger, debug: bool) -> None:
    """Compare default methods with tuned ALNS-OC over one or more seeds."""

    config = json.loads(Path(best_config_path).read_text(encoding="utf-8"))
    rows = []
    tuned_rows = []
    for seed in seeds:
        logger.info("Final tuned comparison seed=%s", seed)
        rng = set_seed(seed)
        # Baselines khong ngau nhien nhung van ghi theo seed de bang so sanh co cung cau truc.
        baseline_solutions = run_baselines(context, logger)
        initial = regret_insertion_initial_solution(context, logger)
        base_solution, _base_hist, _ = run_alns(initial, context, iterations, rng, variant="base", logger=logger, debug=debug)
        default_rng = set_seed(seed)
        default_solution, _default_hist, _ = run_alns(initial, context, iterations, default_rng, variant="oc", logger=logger, debug=debug)
        tuned_context = _apply_tuned_config(context, config)
        tuned_rng = set_seed(seed)
        tuned_solution, _tuned_hist, _ = run_alns(initial, tuned_context, iterations, tuned_rng, variant="oc", logger=logger, debug=debug)
        methods = {
            **baseline_solutions,
            "ALNS-Base": base_solution,
            "ALNS-OC default": default_solution,
            "ALNS-OC tuned": tuned_solution,
        }
        for method, solution in methods.items():
            row = {"method": method, "seed": seed}
            row.update(solution.metrics)
            rows.append(row)
        tuned_row = {"seed": seed, "config_id": config.get("config_id", "")}
        tuned_row.update(tuned_solution.metrics)
        tuned_rows.append(tuned_row)

    metrics_dir = Path(out_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    final = pd.DataFrame(rows)
    final.to_csv(metrics_dir / "final_method_comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(tuned_rows).to_csv(metrics_dir / "final_tuned_repeated_runs.csv", index=False, encoding="utf-8-sig")
    metric_cols = [c for c in final.columns if c not in {"method", "seed"}]
    summary = final.groupby("method")[metric_cols].agg(["mean", "std"]).reset_index()
    summary.columns = ["_".join([str(x) for x in col if x]) for col in summary.columns.to_flat_index()]
    summary.to_csv(metrics_dir / "final_method_comparison_summary.csv", index=False, encoding="utf-8-sig")
    _make_final_plots(final, metrics_dir, logger)
    print("\nFinal tuned comparison exported:")
    print(f"- {metrics_dir / 'final_method_comparison.csv'}")
    print(f"- {metrics_dir / 'final_method_comparison_summary.csv'}")
    print(f"- {metrics_dir / 'final_tuned_repeated_runs.csv'}")


def _make_final_plots(final: pd.DataFrame, metrics_dir: Path, logger) -> None:
    """Create optional final comparison plots."""

    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        logger.warning("matplotlib not available; skipping final plots: %s", exc)
        return
    grouped = final.groupby("method").mean(numeric_only=True).reset_index()
    plt.figure(figsize=(8, 4))
    plt.bar(grouped["method"], grouped["objective"])
    plt.xticks(rotation=25, ha="right")
    plt.ylabel("Mean objective")
    plt.tight_layout()
    plt.savefig(metrics_dir / "final_method_comparison_objective.png", dpi=150)
    plt.close()
    plt.figure(figsize=(8, 4))
    plt.bar(grouped["method"], grouped["completion_rate"])
    plt.xticks(rotation=25, ha="right")
    plt.ylabel("Mean completion rate")
    plt.tight_layout()
    plt.savefig(metrics_dir / "final_method_comparison_completion.png", dpi=150)
    plt.close()


if __name__ == "__main__":
    main()
