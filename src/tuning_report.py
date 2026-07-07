"""Aggregate and report parameter tuning results."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd


PARAM_COLS = [
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
]


def aggregate_tuning_results(output_dir: str | Path, logger: logging.Logger | None = None) -> pd.DataFrame:
    """Aggregate raw tuning rows by config_id and write summary artifacts."""

    logger = logger or logging.getLogger("delivery_alns")
    tuning_dir = Path(output_dir) / "tuning"
    raw_path = tuning_dir / "tuning_results_raw.csv"
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)
    raw = pd.read_csv(raw_path)
    success = raw[raw["status"] == "success"].copy()
    if success.empty:
        raise ValueError("No successful tuning rows to aggregate.")

    # Raw giu tung lan chay tung seed; summary gom nhieu seed de tranh ket luan tu mot run may rui.
    grouped = success.groupby("config_id")
    summary = grouped.agg(
        n_seeds=("seed", "nunique"),
        mean_objective=("objective", "mean"),
        std_objective=("objective", "std"),
        mean_delivered_orders=("delivered_orders", "mean"),
        mean_undelivered_orders=("undelivered_orders", "mean"),
        mean_completion_rate=("completion_rate", "mean"),
        mean_total_distance=("total_distance", "mean"),
        mean_total_waiting_time=("total_waiting_time", "mean"),
        mean_postponement_penalty=("postponement_penalty", "mean"),
        mean_min_slack=("min_slack", "mean"),
        mean_average_delivery_day=("average_delivery_day", "mean"),
        mean_runtime_seconds=("runtime_seconds", "mean"),
    ).reset_index()
    attempts = raw.groupby("config_id")["seed"].count().rename("attempts")
    successes = success.groupby("config_id")["seed"].count().rename("successes")
    summary = summary.merge(attempts, on="config_id").merge(successes, on="config_id")
    summary["success_rate"] = summary["successes"] / summary["attempts"]

    params = success.groupby("config_id")[PARAM_COLS].first().reset_index()
    summary = summary.merge(params, on="config_id")
    summary["std_objective"] = summary["std_objective"].fillna(0.0)

    # Ranking uu tien completion truoc objective vi objective thap khong co y nghia neu bo sot don.
    summary = summary.sort_values(
        [
            "mean_completion_rate",
            "mean_undelivered_orders",
            "mean_objective",
            "mean_postponement_penalty",
            "mean_total_distance",
            "mean_runtime_seconds",
        ],
        ascending=[False, True, True, True, True, True],
    ).reset_index(drop=True)
    summary.insert(0, "rank_by_objective", range(1, len(summary) + 1))

    columns = [
        "rank_by_objective",
        "config_id",
        "n_seeds",
        "success_rate",
        "mean_objective",
        "std_objective",
        "mean_delivered_orders",
        "mean_undelivered_orders",
        "mean_completion_rate",
        "mean_total_distance",
        "mean_total_waiting_time",
        "mean_postponement_penalty",
        "mean_min_slack",
        "mean_average_delivery_day",
        "mean_runtime_seconds",
        *PARAM_COLS,
    ]
    summary = summary[columns]
    summary.to_csv(tuning_dir / "tuning_results_summary.csv", index=False, encoding="utf-8-sig")
    summary.head(10).to_csv(tuning_dir / "top_10_configs.csv", index=False, encoding="utf-8-sig")

    best = summary.iloc[0].to_dict()
    best_config = {key: best[key] for key in ["config_id", *PARAM_COLS]}
    (tuning_dir / "best_config.json").write_text(json.dumps(best_config, indent=2), encoding="utf-8")
    _make_tuning_plots(success, summary, tuning_dir, logger)
    return summary


def _make_tuning_plots(raw_success: pd.DataFrame, summary: pd.DataFrame, tuning_dir: Path, logger: logging.Logger) -> None:
    """Create optional tuning plots."""

    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        logger.warning("matplotlib not available; skipping tuning plots: %s", exc)
        return
    plt.figure(figsize=(7, 4))
    raw_success["objective"].plot(kind="hist", bins=20)
    plt.xlabel("Objective")
    plt.tight_layout()
    plt.savefig(tuning_dir / "tuning_objective_distribution.png", dpi=150)
    plt.close()

    plt.figure(figsize=(6, 4))
    plt.scatter(raw_success["postponement_penalty"], raw_success["total_distance"], alpha=0.7)
    plt.xlabel("Postponement penalty")
    plt.ylabel("Total distance")
    plt.tight_layout()
    plt.savefig(tuning_dir / "tuning_postponement_vs_distance.png", dpi=150)
    plt.close()

    plt.figure(figsize=(8, 4))
    top = summary.head(10)
    plt.bar(top["config_id"], top["mean_objective"])
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Mean objective")
    plt.tight_layout()
    plt.savefig(tuning_dir / "top_10_objective.png", dpi=150)
    plt.close()
