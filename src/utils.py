"""Small shared helpers used across the project."""

from __future__ import annotations

import logging
import math
import os
import random
from pathlib import Path
from typing import Iterable

import numpy as np


def time_to_minutes(value: str | int | float) -> int:
    """Convert HH:MM text to minutes after midnight."""

    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return int(value)
    text = str(value).strip()
    if ":" not in text:
        raise ValueError(f"Invalid HH:MM time value: {value!r}")
    hour, minute = text.split(":", 1)
    return int(hour) * 60 + int(minute)


def minutes_to_time(value: float | int | None) -> str:
    """Format minutes after midnight as HH:MM."""

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    value = int(round(value))
    hour = value // 60
    minute = value % 60
    return f"{hour:02d}:{minute:02d}"


def ensure_dirs(out_dir: str | os.PathLike[str]) -> dict[str, Path]:
    """Create output directories and return their paths."""

    root = Path(out_dir)
    paths = {
        "root": root,
        "schedules": root / "schedules",
        "metrics": root / "metrics",
        "logs": root / "logs",
        "tuning": root / "tuning",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def setup_logging(out_dir: str | os.PathLike[str], debug: bool = False) -> logging.Logger:
    """Configure console and file logging for a run."""

    paths = ensure_dirs(out_dir)
    logger = logging.getLogger("delivery_alns")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(paths["logs"] / "alns_run.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(stream_handler)
    return logger


def set_seed(seed: int) -> random.Random:
    """Seed Python and NumPy random generators and return a local RNG."""

    random.seed(seed)
    np.random.seed(seed)
    return random.Random(seed)


def roulette_choice(weights: dict[str, float], rng: random.Random) -> str:
    """Select one key with probability proportional to its non-negative weight."""

    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0:
        return rng.choice(list(weights.keys()))
    pick = rng.random() * total
    cumulative = 0.0
    for key, weight in weights.items():
        cumulative += max(0.0, weight)
        if cumulative >= pick:
            return key
    return next(reversed(weights))


def chunked(iterable: Iterable, size: int) -> Iterable[list]:
    """Yield lists of at most size items."""

    bucket = []
    for item in iterable:
        bucket.append(item)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket
