"""HTTP API for Orbita.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

import os
from datetime import datetime
from functools import lru_cache

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from timezonefinder import TimezoneFinder

from .astrology import calculate_natal_chart

app = FastAPI(
    title="Orbita API",
    version="0.1.0",
    license_info={
        "name": "GNU Affero General Public License v3.0 or later",
        "identifier": "AGPL-3.0-or-later",
    },
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ORBITA_ALLOWED_ORIGINS", "http://localhost:4173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
timezone_finder = TimezoneFinder(in_memory=True)


class NatalChartRequest(BaseModel):
    birth_datetime: datetime = Field(
        examples=["1990-01-01T12:00:00"],
        description="Local birth date and time without a UTC offset",
    )
    timezone: str = Field(examples=["Europe/Paris"])
    latitude: float = Field(ge=-90, le=90, examples=[48.8566])
    longitude: float = Field(ge=-180, le=180, examples=[2.3522])
    house_system: str = Field(default="P", min_length=1, max_length=1)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@lru_cache(maxsize=256)
def _timezone_at(latitude: float, longitude: float) -> str | None:
    return timezone_finder.timezone_at(lat=latitude, lng=longitude)


@app.get("/v1/places/search")
async def search_places(q: str) -> list[dict]:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Enter at least two characters")
    headers = {"User-Agent": os.getenv("NOMINATIM_USER_AGENT", "Orbita/0.1")}
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
        "accept-language": "ru",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                os.getenv("GEOCODER_URL", "https://nominatim.openstreetmap.org/search"),
                params=params,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Place search is temporarily unavailable") from exc
    places = []
    for item in response.json():
        latitude = float(item["lat"])
        longitude = float(item["lon"])
        timezone_name = _timezone_at(round(latitude, 4), round(longitude, 4))
        if timezone_name:
            places.append({
                "label": item["display_name"],
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone_name,
            })
    return places


@app.post("/v1/natal-chart")
def natal_chart(request: NatalChartRequest) -> dict:
    try:
        return calculate_natal_chart(
            birth_datetime=request.birth_datetime,
            timezone_name=request.timezone,
            latitude=request.latitude,
            longitude=request.longitude,
            house_system=request.house_system,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
