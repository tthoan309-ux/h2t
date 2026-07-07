"""Distance and travel-time preprocessing."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_matrices(locations_df: pd.DataFrame, speed_kmph: float = 50.0) -> dict:
    """Compute Euclidean distance and travel-time matrices."""

    ids = locations_df["location_id"].astype(str).tolist()
    coords = locations_df[["x_km", "y_km"]].astype(float).to_numpy()
    # Tọa độ đề bài đã cho theo km, nên khoảng cách Euclid là mô hình tự nhiên.
    diff = coords[:, None, :] - coords[None, :, :]
    distance = np.sqrt(np.sum(diff * diff, axis=2))
    # Xe không vượt 50 km/h: 1 km mất 60/50 = 1.2 phút. Ràng buộc này quyết định khả thi time window.
    travel_time = distance / speed_kmph * 60.0
    id_to_idx = {cid: idx for idx, cid in enumerate(ids)}
    return {"ids": ids, "id_to_idx": id_to_idx, "distance": distance, "travel_time": travel_time}


def matrix_lookup(matrix: np.ndarray, id_to_idx: dict[str, int], a: str, b: str) -> float:
    """Return matrix value for two location ids."""

    return float(matrix[id_to_idx[a], id_to_idx[b]])
