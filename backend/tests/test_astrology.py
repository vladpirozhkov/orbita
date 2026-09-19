from datetime import datetime

from app.astrology import calculate_natal_chart


def test_demo_chart_is_deterministic():
    args = {
        "birth_datetime": datetime(1990, 1, 1, 12, 0),
        "timezone_name": "Europe/Paris",
        "latitude": 48.8566,
        "longitude": 2.3522,
    }
    first = calculate_natal_chart(**args)
    second = calculate_natal_chart(**args)

    assert first == second
    assert first["planets"]["Sun"]["sign"] == "Capricorn"
    assert len(first["houses"]) == 12
    assert 0 <= first["angles"]["ascendant"] < 360
    assert first["engine"]["name"] == "Swiss Ephemeris"


def test_all_planet_longitudes_are_normalized():
    chart = calculate_natal_chart(
        datetime(1985, 7, 15, 8, 30),
        "America/New_York",
        40.7128,
        -74.0060,
    )
    assert all(0 <= row["longitude"] < 360 for row in chart["planets"].values())
