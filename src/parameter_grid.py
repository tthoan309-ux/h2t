"""Parameter grids and sampled searches for ALNS-OC tuning."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from pathlib import Path
from typing import Any


QUICK_GRID = {
    "eta_oc": [0.2, 0.5, 0.8],
    "theta_postponement": [500, 1000],
    "phi_delivery_day": [250, 500],
    "rho_operator_learning": [0.1],
    "temperature_initial": [500, 1000],
    "cooling_rate": [0.995],
    "removal_fraction_min": [0.05],
    "removal_fraction_max": [0.15],
    "use_slack_penalty": [True],
    "use_early_day_repair": [True],
    "use_relocate_to_earlier_day": [True],
}

FULL_GRID = {
    "eta_oc": [0.1, 0.3, 0.5, 0.8, 1.2],
    "theta_postponement": [500, 1000, 2000, 5000],
    "phi_delivery_day": [0, 250, 500, 1000],
    "rho_operator_learning": [0.05, 0.1, 0.2],
    "temperature_initial": [300, 500, 1000, 2000],
    "cooling_rate": [0.990, 0.995, 0.998],
    "removal_fraction_min": [0.03, 0.05, 0.08],
    "removal_fraction_max": [0.12, 0.15, 0.20],
    "use_slack_penalty": [True, False],
    "use_early_day_repair": [True, False],
    "use_relocate_to_earlier_day": [True, False],
}


def get_parameter_grid(
    mode: str,
    grid_file: str | None = None,
    search_strategy: str = "grid",
    n_configs: int | None = None,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Return deterministic parameter configurations for tuning."""

    grid = _load_grid(mode, grid_file)
    if search_strategy == "grid":
        # Full factorial cua full grid tao hon 200k config; chi nen dung grid cho quick/custom nho.
        configs = _expand_grid(grid)
        return configs[:n_configs] if n_configs else configs
    if n_configs is None:
        raise ValueError("--n-configs is required for random or latin search.")
    if search_strategy == "random":
        return _sample_random(grid, n_configs, seed)
    if search_strategy == "latin":
        return _sample_latin(grid, n_configs, seed)
    raise ValueError(f"Unknown search strategy: {search_strategy}")


def count_parameter_space(mode: str, grid_file: str | None = None) -> int:
    """Count valid full-factorial combinations without materializing them."""

    grid = _load_grid(mode, grid_file)
    count = 0
    keys = sorted(grid)
    for values in itertools.product(*(grid[key] for key in keys)):
        config = dict(zip(keys, values))
        if _is_valid_config(config):
            count += 1
    return count


def default_search_strategy(mode: str, requested: str | None) -> str:
    """Choose default strategy: random for full, grid otherwise."""

    if requested:
        return requested
    return "random" if mode == "full" else "grid"


def _load_grid(mode: str, grid_file: str | None = None) -> dict[str, list[Any]]:
    """Load a parameter value space."""

    if mode == "quick":
        return QUICK_GRID
    if mode == "full":
        return FULL_GRID
    if mode == "custom":
        if not grid_file:
            raise ValueError("--grid-file is required when --tune-mode custom")
        return json.loads(Path(grid_file).read_text(encoding="utf-8"))
    raise ValueError(f"Unknown tune mode: {mode}")


def _expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a dictionary of value lists into deterministic config dictionaries."""

    keys = sorted(grid)
    configs: list[dict[str, Any]] = []
    for values in itertools.product(*(grid[key] for key in keys)):
        config = dict(zip(keys, values))
        if not _is_valid_config(config):
            continue
        config["config_id"] = make_config_id(config)
        configs.append(config)
    configs.sort(key=lambda c: c["config_id"])
    return configs


def _sample_random(grid: dict[str, list[Any]], n_configs: int, seed: int) -> list[dict[str, Any]]:
    """Randomly sample unique parameter combinations from the full value space."""

    rng = random.Random(seed)
    max_space = count_valid_grid(grid)
    target = min(n_configs, max_space)
    configs_by_id: dict[str, dict[str, Any]] = {}
    attempts = 0
    # Random search phu hop hon full grid vi chi can tim vung tham so tot, khong can thu moi to hop.
    while len(configs_by_id) < target and attempts < target * 200:
        attempts += 1
        config = {key: rng.choice(values) for key, values in grid.items()}
        if not _is_valid_config(config):
            continue
        config["config_id"] = make_config_id(config)
        configs_by_id.setdefault(config["config_id"], config)
    if len(configs_by_id) < target:
        for config in _expand_grid(grid):
            configs_by_id.setdefault(config["config_id"], config)
            if len(configs_by_id) >= target:
                break
    return sorted(configs_by_id.values(), key=lambda c: c["config_id"])


def _sample_latin(grid: dict[str, list[Any]], n_configs: int, seed: int) -> list[dict[str, Any]]:
    """Sample a simple discrete Latin-hypercube-like set of configurations."""

    rng = random.Random(seed)
    keys = sorted(grid)
    max_space = count_valid_grid(grid)
    target = min(n_configs, max_space)
    configs_by_id: dict[str, dict[str, Any]] = {}
    for i in range(target * 20):
        config = {}
        for key in keys:
            values = list(grid[key])
            offset = rng.randrange(len(values))
            # Lay mau phan tang: moi tham so xoay deu qua cac gia tri thay vi boc ngau nhien hoan toan.
            config[key] = values[(i + offset) % len(values)]
        if not _is_valid_config(config):
            continue
        config["config_id"] = make_config_id(config)
        configs_by_id.setdefault(config["config_id"], config)
        if len(configs_by_id) >= target:
            break
    if len(configs_by_id) < target:
        for config in _sample_random(grid, target, seed + 1009):
            configs_by_id.setdefault(config["config_id"], config)
            if len(configs_by_id) >= target:
                break
    return sorted(configs_by_id.values(), key=lambda c: c["config_id"])


def count_valid_grid(grid: dict[str, list[Any]]) -> int:
    """Count valid combinations for an already loaded grid."""

    keys = sorted(grid)
    count = 0
    for values in itertools.product(*(grid[key] for key in keys)):
        if _is_valid_config(dict(zip(keys, values))):
            count += 1
    return count


def _is_valid_config(config: dict[str, Any]) -> bool:
    """Return whether a configuration satisfies basic parameter constraints."""

    # removal_fraction_min > max khong co y nghia vi destroy khong the boc nhieu hon tran.
    return float(config["removal_fraction_min"]) <= float(config["removal_fraction_max"])


def make_config_id(config: dict[str, Any]) -> str:
    """Create a short deterministic hash from sorted parameter values."""

    payload = json.dumps({k: v for k, v in sorted(config.items()) if k != "config_id"}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


PARAMETER_EXPLANATIONS = {
    "eta_oc": "Do manh cua opportunity cost: cao hon thi uu tien don co rui ro bi mat kha thi.",
    "theta_postponement": "Phat khi chen lam tang postponement; quan trong de OC khong day don sang ngay muon.",
    "phi_delivery_day": "Phat ngay giao muon, keo don ve cac ngay som neu kha thi.",
    "rho_operator_learning": "Toc do hoc trong cap nhat trong so destroy/repair operator.",
    "temperature_initial": "Nhiet do ban dau cua simulated annealing.",
    "cooling_rate": "Toc do giam nhiet do sau moi vong lap.",
    "removal_fraction_min": "Ti le don toi thieu bi pha trong destroy step.",
    "removal_fraction_max": "Ti le don toi da bi pha trong destroy step.",
    "use_slack_penalty": "Bat/tat phat slack thap trong objective/repair.",
    "use_early_day_repair": "Bat/tat repair uu tien ngay som.",
    "use_relocate_to_earlier_day": "Bat/tat local search keo don sang ngay som hon.",
}
