"""Deterministic natal-chart calculations backed by Swiss Ephemeris.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

import swisseph as swe

SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
    "True Node": swe.TRUE_NODE,
}

ASPECTS = {
    "conjunction": (0.0, 8.0),
    "sextile": (60.0, 4.0),
    "square": (90.0, 6.0),
    "trine": (120.0, 6.0),
    "opposition": (180.0, 8.0),
}


@dataclass(frozen=True)
class Position:
    longitude: float
    latitude: float
    speed: float
    sign: str
    degree_in_sign: float
    retrograde: bool


def _position(values: tuple[float, ...]) -> Position:
    longitude = values[0] % 360
    return Position(
        longitude=round(longitude, 6),
        latitude=round(values[1], 6),
        speed=round(values[3], 6),
        sign=SIGNS[int(longitude // 30)],
        degree_in_sign=round(longitude % 30, 6),
        retrograde=values[3] < 0,
    )


def _utc_julian_day(local_dt: datetime, timezone_name: str) -> tuple[float, str]:
    if local_dt.tzinfo is not None:
        raise ValueError("birth_datetime must not contain an offset")
    zone = ZoneInfo(timezone_name)
    utc_dt = local_dt.replace(tzinfo=zone).astimezone(timezone.utc)
    hour = utc_dt.hour + utc_dt.minute / 60 + utc_dt.second / 3600
    return swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour, swe.GREG_CAL), utc_dt.isoformat()


def _angular_distance(a: float, b: float) -> float:
    distance = abs(a - b) % 360
    return min(distance, 360 - distance)


def _house_for(longitude: float, cusps: tuple[float, ...]) -> int:
    normalized = longitude % 360
    for index, start in enumerate(cusps):
        end = cusps[(index + 1) % 12]
        if (normalized - start) % 360 < (end - start) % 360:
            return index + 1
    return 12


def calculate_natal_chart(
    birth_datetime: datetime,
    timezone_name: str,
    latitude: float,
    longitude: float,
    house_system: str = "P",
) -> dict:
    """Calculate planets, Placidus house cusps, angles and major aspects."""
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    if len(house_system) != 1:
        raise ValueError("house_system must be a one-character Swiss Ephemeris code")

    jd_ut, utc_datetime = _utc_julian_day(birth_datetime, timezone_name)
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    positions: dict[str, Position] = {}

    for name, body in PLANETS.items():
        values, _ = swe.calc_ut(jd_ut, body, flags)
        positions[name] = _position(values)

    cusps, angles = swe.houses_ex(jd_ut, latitude, longitude, house_system.encode())
    houses = [
        {
            "number": index + 1,
            "longitude": round(value % 360, 6),
            "sign": SIGNS[int((value % 360) // 30)],
            "degree_in_sign": round(value % 30, 6),
        }
        for index, value in enumerate(cusps)
    ]

    aspect_rows = []
    for (left_name, left), (right_name, right) in combinations(positions.items(), 2):
        separation = _angular_distance(left.longitude, right.longitude)
        for aspect_name, (exact, max_orb) in ASPECTS.items():
            orb = abs(separation - exact)
            if orb <= max_orb:
                aspect_rows.append({
                    "from": left_name,
                    "to": right_name,
                    "type": aspect_name,
                    "orb": round(orb, 4),
                })
                break

    return {
        "engine": {"name": "Swiss Ephemeris", "version": swe.version},
        "input": {
            "local_datetime": birth_datetime.isoformat(),
            "timezone": timezone_name,
            "utc_datetime": utc_datetime,
            "latitude": latitude,
            "longitude": longitude,
            "house_system": house_system,
        },
        "julian_day_ut": round(jd_ut, 8),
        "planets": {
            name: {**asdict(value), "house": _house_for(value.longitude, cusps)}
            for name, value in positions.items()
        },
        "houses": houses,
        "angles": {
            "ascendant": round(angles[0] % 360, 6),
            "midheaven": round(angles[1] % 360, 6),
            "armc": round(angles[2] % 360, 6),
            "vertex": round(angles[3] % 360, 6),
        },
        "aspects": sorted(aspect_rows, key=lambda row: row["orb"]),
    }
