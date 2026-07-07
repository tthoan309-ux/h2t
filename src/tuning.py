"""Grid-search runner for ALNS-OC parameter tuning."""

from __future__ import annotations

import csv
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

from .alns import run_alns
from .initial_solution import regret_insertion_initial_solution
from .tuning_report import aggregate_tuning_results
from .utils import set_seed

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover - fallback path depends on optional dependency
    tqdm = None


RAW_COLUMNS = [
    "config_id",
    "seed",
    "eta_oc",
    "theta_postponement",
    "phi_delivery_day",
    "rho_operator_learning",
    "temperature_initial",
    "cooling_rate",
    "removal_fraction_min",
    "removal_fraction_max",
    "use_slack_penalty",
    "use_early_day_repair",
    "use_relocate_to_earlier_day",
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
    "accepted_solutions",
    "best_iteration",
    "status",
    "error_message",
]


def run_grid_search(
    data_bundle: dict[str, Any],
    output_dir: str | Path,
    base_config: dict[str, Any],
    param_grid: list[dict[str, Any]],
    seeds: list[int],
    iterations: int,
    resume: bool = False,
    max_configs: int | None = None,
    parallel: int | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Run ALNS-OC grid search and write raw/summary tuning outputs."""

    logger = logger or logging.getLogger("delivery_alns")
    tuning_dir = Path(output_dir) / "tuning"
    tuning_dir.mkdir(parents=True, exist_ok=True)
    raw_path = tuning_dir / "tuning_results_raw.csv"
    _ensure_raw_file(raw_path)

    configs = param_grid[: max_configs or len(param_grid)]
    completed = _completed_pairs(raw_path) if resume else set()
    jobs = [(config, seed) for config in configs for seed in seeds if (config["config_id"], seed) not in completed]
    total_jobs = len(jobs)
    logger.info("Tuning started: configs=%d seeds=%s jobs=%d resume=%s parallel=%s", len(configs), seeds, total_jobs, resume, parallel)

    # Dung chung initial solution theo seed de khong phai dung lai nghiem khoi tao cho moi config.
    # Feasibility cua initial khong phu thuoc eta/theta/phi, nen tai su dung giup tuning nhanh hon rat nhieu.
    initial_by_seed = _build_initial_solutions(data_bundle, base_config, seeds, logger)

    # Nhieu seed la can thiet vi ALNS co thanh phan ngau nhien; mot debug run co the qua may hoac qua xui.
    progress = _progress_bar(total_jobs, "Tuning configs")
    if parallel and parallel > 1:
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = [executor.submit(_run_one_config_seed, data_bundle, base_config, config, seed, iterations, logger, initial_by_seed.get(seed)) for config, seed in jobs]
            for idx, future in enumerate(as_completed(futures), start=1):
                row = future.result()
                _append_row(raw_path, row)
                _advance_progress(progress, row)
                logger.info("Tuning progress %d/%d config=%s seed=%s status=%s", idx, total_jobs, row["config_id"], row["seed"], row["status"])
    else:
        for idx, (config, seed) in enumerate(jobs, start=1):
            row = _run_one_config_seed(data_bundle, base_config, config, seed, iterations, logger, initial_by_seed.get(seed))
            _append_row(raw_path, row)
            _advance_progress(progress, row)
            logger.info("Tuning progress %d/%d config=%s seed=%s status=%s", idx, total_jobs, row["config_id"], seed, row["status"])
    _close_progress(progress)

    summary = aggregate_tuning_results(output_dir, logger)
    best = summary.iloc[0]
    logger.info(
        "Best tuning config=%s mean_objective=%.2f mean_completion=%.4f mean_postponement=%.2f mean_distance=%.2f",
        best["config_id"],
        best["mean_objective"],
        best["mean_completion_rate"],
        best["mean_postponement_penalty"],
        best["mean_total_distance"],
    )
    return summary


def _run_one_config_seed(
    data_bundle: dict[str, Any],
    base_config: dict[str, Any],
    config: dict[str, Any],
    seed: int,
    iterations: int,
    logger: logging.Logger,
    initial_solution=None,
) -> dict[str, Any]:
    """Run one config/seed pair and return one raw result row."""

    row = {col: "" for col in RAW_COLUMNS}
    row.update({key: config.get(key) for key in config if key in RAW_COLUMNS})
    row["config_id"] = config["config_id"]
    row["seed"] = seed
    start = time.perf_counter()
    try:
        context = _context_for_config(data_bundle, base_config, config)
        rng = set_seed(seed)
        initial = initial_solution.copy() if initial_solution is not None else regret_insertion_initial_solution(context, logger)
        solution, history, _ops = run_alns(initial, context, iterations, rng, variant="oc", logger=logger, debug=False)
        row.update(solution.metrics)
        row["objective"] = solution.objective_value
        row["runtime_seconds"] = time.perf_counter() - start
        row["accepted_solutions"] = int(history["accepted"].sum()) if not history.empty and "accepted" in history else 0
        row["best_iteration"] = int(history.loc[history["best_objective"].idxmin(), "iteration"]) if not history.empty else 0
        row["status"] = "success"
        row["error_message"] = ""
    except Exception as exc:
        # Mot config hong khong duoc lam dung toan bo grid; can ghi lai de phan tich sau.
        row["runtime_seconds"] = time.perf_counter() - start
        row["status"] = "failed"
        row["error_message"] = f"{type(exc).__name__}: {exc}"
        logger.error("Tuning run failed config=%s seed=%s\n%s", config["config_id"], seed, traceback.format_exc())
    return row


def _build_initial_solutions(data_bundle: dict[str, Any], base_config: dict[str, Any], seeds: list[int], logger: logging.Logger) -> dict[int, Any]:
    """Build one reusable initial solution per seed before the grid loop."""

    initials = {}
    for seed in seeds:
        # Seed van duoc set de neu initial co thanh phan ngau nhien trong tuong lai thi ket qua van reproducible.
        set_seed(seed)
        context = dict(data_bundle)
        context.update(base_config)
        logger.info("Building reusable initial solution for tuning seed=%s", seed)
        initials[seed] = regret_insertion_initial_solution(context, logger)
    return initials


def _context_for_config(data_bundle: dict[str, Any], base_config: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Merge base context with one tuning configuration."""

    context = dict(data_bundle)
    context.update(base_config)
    context.update(
        {
            "eta_oc": config["eta_oc"],
            "theta_postponement": config["theta_postponement"],
            "phi_delivery_day": config["phi_delivery_day"],
            "rho_operator_learning": config["rho_operator_learning"],
            "temperature_initial": config["temperature_initial"],
            "cooling_rate": config["cooling_rate"],
            "random_min_remove": config["removal_fraction_min"],
            "random_max_remove": config["removal_fraction_max"],
            "use_slack_penalty": config["use_slack_penalty"],
            "use_early_day_repair": config["use_early_day_repair"],
            "use_relocate_to_earlier_day": config["use_relocate_to_earlier_day"],
        }
    )
    return context


def _ensure_raw_file(path: Path) -> None:
    """Create raw CSV with headers if needed."""

    if not path.exists():
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=RAW_COLUMNS).writeheader()


def _append_row(path: Path, row: dict[str, Any]) -> None:
    """Append one raw row immediately so long tuning runs are resumable."""

    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_COLUMNS, extrasaction="ignore")
        writer.writerow(row)


def _completed_pairs(path: Path) -> set[tuple[str, int]]:
    """Return successful config_id/seed pairs already present in raw CSV."""

    if not path.exists():
        return set()
    df = pd.read_csv(path)
    if df.empty:
        return set()
    # Resume quan trong vi full grid co the chay hang gio/ngay; khong nen mat ket qua da xong.
    done = df[df["status"] == "success"]
    return {(str(row.config_id), int(row.seed)) for row in done.itertuples(index=False)}


def _progress_bar(total: int, desc: str):
    """Create a tqdm progress bar when available."""

    if tqdm is None or total <= 0:
        return None
    # Progress bar giup theo doi tuning dai: biet da xong bao nhieu config/seed va config nao dang fail.
    return tqdm(total=total, desc=desc, unit="run", dynamic_ncols=True)


def _advance_progress(progress, row: dict[str, Any]) -> None:
    """Advance the optional progress bar after one config/seed run."""

    if progress is None:
        return
    progress.set_postfix(
        {
            "config": row.get("config_id", ""),
            "seed": row.get("seed", ""),
            "status": row.get("status", ""),
        }
    )
    progress.update(1)


def _close_progress(progress) -> None:
    """Close optional progress bar."""

    if progress is not None:
        progress.close()
