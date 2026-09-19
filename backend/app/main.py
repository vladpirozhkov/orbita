"""HTTP API for Orbita.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .astrology import calculate_natal_chart

app = FastAPI(
    title="Orbita API",
    version="0.1.0",
    license_info={
        "name": "GNU Affero General Public License v3.0 or later",
        "identifier": "AGPL-3.0-or-later",
    },
)


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
