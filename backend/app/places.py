"""Offline city lookup backed by the bundled GeoNames snapshot."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

import geonamescache


_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold().replace("ё", "е"))
    return " ".join("".join(char for char in folded if char.isalnum() or char.isspace()).split())


@lru_cache(maxsize=1)
def _city_index() -> tuple[dict[str, Any], ...]:
    cache = geonamescache.GeonamesCache(min_city_population=5000)
    countries = cache.get_countries()
    indexed: list[dict[str, Any]] = []
    for city in cache.get_cities().values():
        primary = str(city["name"])
        alternates = [str(name) for name in city.get("alternatenames", []) if name]
        cyrillic = [name for name in alternates if _CYRILLIC_RE.search(name)][:8]
        latin = [name for name in alternates if not _CYRILLIC_RE.search(name)][:4]
        names = list(dict.fromkeys([primary, *cyrillic, *latin]))
        normalized_names = tuple(filter(None, (_normalize(name) for name in names)))
        country_code = str(city.get("countrycode", ""))
        country = countries.get(country_code, {}).get("name", country_code)
        indexed.append({
            "names": tuple(names),
            "normalized_names": normalized_names,
            "country": country,
            "country_code": country_code,
            "latitude": float(city["latitude"]),
            "longitude": float(city["longitude"]),
            "timezone": str(city["timezone"]),
            "population": int(city.get("population") or 0),
        })
    return tuple(indexed)


@lru_cache(maxsize=256)
def search_cities(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return ranked cities without making a network request."""

    normalized_query = _normalize(query)
    if len(normalized_query) < 2:
        return []

    matches: list[tuple[int, int, str, dict[str, Any]]] = []
    for city in _city_index():
        ranks = []
        for index, name in enumerate(city["normalized_names"]):
            if name == normalized_query:
                ranks.append((0, index))
            elif name.startswith(normalized_query):
                ranks.append((1, index))
            elif normalized_query in name:
                ranks.append((2, index))
        if not ranks:
            continue
        rank, name_index = min(ranks)
        display_name = city["names"][name_index]
        matches.append((rank, -city["population"], display_name.casefold(), {
            "label": f"{display_name}, {city['country']}",
            "latitude": city["latitude"],
            "longitude": city["longitude"],
            "timezone": city["timezone"],
        }))

    matches.sort(key=lambda item: item[:3])
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, float, float]] = set()
    for _, _, _, place in matches:
        identity = (place["label"], place["latitude"], place["longitude"])
        if identity in seen:
            continue
        seen.add(identity)
        results.append(place)
        if len(results) >= limit:
            break
    return results
