import pandas as pd

from src.distance import build_matrices


def test_euclidean_distance_and_travel_time():
    df = pd.DataFrame(
        {
            "location_id": ["DEPOT", "C1"],
            "x_km": [0, 3],
            "y_km": [0, 4],
        }
    )
    matrices = build_matrices(df, speed_kmph=50)
    assert matrices["distance"][0, 1] == 5
    assert matrices["travel_time"][0, 1] == 6
