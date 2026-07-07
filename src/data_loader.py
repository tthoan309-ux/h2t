"""Input reading and schema normalization."""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

from .utils import time_to_minutes


def _find_csv_root(path: Path) -> Path:
    """Find the folder that contains locations.csv and time_windows.csv."""

    if path.is_file() and path.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="delivery_alns_"))
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        path = tmp
    if (path / "locations.csv").exists() and (path / "time_windows.csv").exists():
        return path
    matches = list(path.rglob("locations.csv"))
    for loc in matches:
        root = loc.parent
        if (root / "time_windows.csv").exists():
            return root
    raise FileNotFoundError(f"Cannot find locations.csv and time_windows.csv under {path}")


def _normalize_columns(df: pd.DataFrame, mapping: dict[str, list[str]], required: list[str], file_name: str) -> pd.DataFrame:
    """Normalize column names by semantic aliases and validate required fields."""

    detected = {c.lower().strip().replace(" ", "_"): c for c in df.columns}
    rename: dict[str, str] = {}
    for target, aliases in mapping.items():
        for alias in [target, *aliases]:
            key = alias.lower().strip().replace(" ", "_")
            if key in detected:
                rename[detected[key]] = target
                break
    out = df.rename(columns=rename).copy()
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(
            f"{file_name} missing required columns {missing}. Detected columns: {list(df.columns)}"
        )
    return out


def load_data(data_path: str | Path, default_service_time: int = 5, logger: logging.Logger | None = None) -> dict:
    """Load and normalize locations and time windows from a zip or folder."""

    logger = logger or logging.getLogger("delivery_alns")
    root = _find_csv_root(Path(data_path))
    locations_raw = pd.read_csv(root / "locations.csv")
    windows_raw = pd.read_csv(root / "time_windows.csv")

    # Các alias giúp code chịu được dữ liệu thi có tên cột khác nhau.
    loc_map = {
        "location_id": ["id", "customer_id", "node_id"],
        "location_name": ["name", "customer_name"],
        "x_km": ["x", "x_coord", "longitude"],
        "y_km": ["y", "y_coord", "latitude"],
        "demand_kg": ["demand", "quantity", "qty"],
        "service_time": ["service_minutes", "service_duration"],
    }
    tw_map = {
        "location_id": ["id", "customer_id"],
        "day_of_week": ["day", "weekday"],
        "start_time": ["start", "window_start"],
        "end_time": ["end", "window_end"],
    }
    locations = _normalize_columns(locations_raw, loc_map, ["location_id", "x_km", "y_km"], "locations.csv")
    windows = _normalize_columns(windows_raw, tw_map, ["location_id", "day_of_week", "start_time", "end_time"], "time_windows.csv")

    if "location_name" not in locations.columns:
        locations["location_name"] = locations["location_id"].astype(str)
    if "demand_kg" not in locations.columns:
        locations["demand_kg"] = 0.0
    if "service_time" not in locations.columns:
        locations["service_time"] = default_service_time

    locations["location_id"] = locations["location_id"].astype(str)
    locations["location_name"] = locations["location_name"].astype(str)
    locations["service_time"] = locations["service_time"].fillna(default_service_time).astype(int)
    windows["location_id"] = windows["location_id"].astype(str)
    windows["day_of_week"] = windows["day_of_week"].astype(int)
    windows["start_min"] = windows["start_time"].apply(time_to_minutes)
    windows["end_min"] = windows["end_time"].apply(time_to_minutes)
    windows = windows.sort_values(["location_id", "day_of_week", "start_min", "end_min"]).reset_index(drop=True)

    # Xác định depot bằng id/name quen thuộc; nếu không có thì dùng dòng đầu.
    depot_candidates = locations[
        locations["location_id"].str.lower().isin(["depot", "0", "warehouse", "kho"])
        | locations["location_name"].str.lower().str.contains("kho|depot|warehouse", regex=True)
    ]
    if depot_candidates.empty:
        depot_id = str(locations.iloc[0]["location_id"])
        logger.warning("No explicit depot found; using first row as depot: %s", depot_id)
    else:
        depot_id = str(depot_candidates.iloc[0]["location_id"])
    customer_ids = [cid for cid in locations["location_id"].tolist() if cid != depot_id]
    no_window = sorted(set(customer_ids) - set(windows["location_id"].unique()))

    logger.info(
        "Data summary: locations=%d, customers=%d, time_windows=%d, days=%s, customers_without_windows=%d",
        len(locations),
        len(customer_ids),
        len(windows),
        sorted(windows["day_of_week"].unique().tolist()),
        len(no_window),
    )
    if no_window:
        logger.warning("Customers without any time window: %s", no_window[:20])
    return {
        "locations_df": locations.reset_index(drop=True),
        "time_windows_df": windows,
        "depot_id": depot_id,
        "customer_ids": customer_ids,
        "data_root": root,
    }
