from datetime import datetime

from app.astrology import calculate_daily_forecast, calculate_natal_chart, interpret_natal_chart


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
    assert 1 <= first["planets"]["Sun"]["house"] <= 12
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
    assert all(1 <= row["house"] <= 12 for row in chart["planets"].values())


def test_interpretation_and_daily_forecast_are_grounded_in_chart():
    chart = calculate_natal_chart(
        datetime(1990, 1, 1, 12, 0),
        "Europe/Paris",
        48.8566,
        2.3522,
    )
    interpretation = interpret_natal_chart(chart)
    forecast = calculate_daily_forecast(chart, datetime(2026, 9, 20, 12, 0))

    assert "Солнце" in interpretation["identity"]
    assert len(interpretation["cards"]) >= 7
    assert {card["key"] for card in interpretation["cards"]} >= {"identity", "relationships", "career", "growth"}
    assert forecast["date"] == "2026-09-20"
    assert all(1 <= value <= 10 for value in forecast["scores"].values())
    assert all(row["orb"] <= 2.5 for row in forecast["transits"])
