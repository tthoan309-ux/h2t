from src.utils import time_to_minutes


def test_hhmm_conversion_works():
    assert time_to_minutes("08:30") == 510
    assert time_to_minutes("17:45") == 1065
