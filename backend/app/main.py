"""HTTP API for Orbita.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

import os
from datetime import date, datetime, time
from functools import lru_cache
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from timezonefinder import TimezoneFinder

from .astrology import calculate_daily_forecast, calculate_natal_chart, interpret_natal_chart
from .analytics import (
    ALLOWED_EVENT_NAMES,
    AnalyticsStorageError,
    InvalidTelegramData,
    store_analytics_batch,
    validate_telegram_init_data,
)
from .notifications import (
    NotificationStorageError,
    NotificationTestCooldownError,
    dispatch_due_notifications,
    notification_status,
    save_notification_subscription,
    send_test_notification,
)

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


class AnalyticsEvent(BaseModel):
    event_id: UUID
    name: str = Field(min_length=1, max_length=48)
    session_id: UUID
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalyticsBatchRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)
    platform: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    events: list[AnalyticsEvent] = Field(min_length=1, max_length=20)


class TelegramRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class NotificationSubscriptionRequest(TelegramRequest):
    enabled: bool
    birth_date: date | None = None
    birth_time: time | None = None
    timezone: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    preferred_hour: int = Field(default=9, ge=0, le=23)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/analytics/events", status_code=202)
async def analytics_events(request: AnalyticsBatchRequest) -> dict:
    bot_token = os.getenv("ORBITA_BOT_TOKEN", "")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_secret_key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not bot_token or not supabase_url or not supabase_secret_key:
        raise HTTPException(status_code=503, detail="Analytics is not configured")
    invalid_names = sorted({event.name for event in request.events} - ALLOWED_EVENT_NAMES)
    if invalid_names:
        raise HTTPException(status_code=422, detail="Unsupported analytics event")
    try:
        identity = validate_telegram_init_data(
            request.init_data,
            bot_token,
            max_age_seconds=int(os.getenv("TELEGRAM_INIT_DATA_MAX_AGE_SECONDS", "86400")),
        )
        stored = await store_analytics_batch(
            supabase_url=supabase_url,
            supabase_secret_key=supabase_secret_key,
            identity=identity,
            events=[event.model_dump(mode="json") for event in request.events],
            platform=request.platform,
            app_version=request.app_version,
        )
    except InvalidTelegramData as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (AnalyticsStorageError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Analytics is temporarily unavailable") from exc
    return {"accepted": stored}


def _telegram_identity(init_data: str):
    bot_token = os.getenv("ORBITA_BOT_TOKEN", "")
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram integration is not configured")
    try:
        return validate_telegram_init_data(
            init_data,
            bot_token,
            max_age_seconds=int(os.getenv("TELEGRAM_INIT_DATA_MAX_AGE_SECONDS", "86400")),
        )
    except (InvalidTelegramData, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Telegram session is invalid") from exc


def _supabase_settings() -> tuple[str, str]:
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_secret_key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not supabase_url or not supabase_secret_key:
        raise HTTPException(status_code=503, detail="Notification storage is not configured")
    return supabase_url, supabase_secret_key


@app.post("/v1/notifications/status")
async def get_notification_status(request: TelegramRequest) -> dict:
    identity = _telegram_identity(request.init_data)
    supabase_url, supabase_secret_key = _supabase_settings()
    try:
        status = await notification_status(
            supabase_url=supabase_url,
            supabase_secret_key=supabase_secret_key,
            user_key=identity.user_key,
        )
    except NotificationStorageError as exc:
        raise HTTPException(status_code=502, detail="Notification settings are unavailable") from exc
    return status


@app.post("/v1/notifications/subscription")
async def update_notification_subscription(request: NotificationSubscriptionRequest) -> dict:
    identity = _telegram_identity(request.init_data)
    supabase_url, supabase_secret_key = _supabase_settings()
    profile = None
    if request.enabled:
        if (
            not request.birth_date
            or not request.birth_time
            or not request.timezone
            or request.latitude is None
            or request.longitude is None
        ):
            raise HTTPException(status_code=422, detail="Complete birth profile is required")
        if request.birth_date and request.birth_date > date.today():
            raise HTTPException(status_code=422, detail="Birth date cannot be in the future")
        try:
            ZoneInfo(request.timezone or "")
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="Unknown timezone") from exc
        profile = {
            "birth_date": request.birth_date.isoformat(),
            "birth_time": request.birth_time.isoformat(),
            "timezone": request.timezone,
            "latitude": request.latitude,
            "longitude": request.longitude,
            "preferred_hour": request.preferred_hour,
        }
    try:
        enabled = await save_notification_subscription(
            supabase_url=supabase_url,
            supabase_secret_key=supabase_secret_key,
            identity=identity,
            profile=profile,
            enabled=request.enabled,
        )
    except NotificationStorageError as exc:
        raise HTTPException(status_code=502, detail="Notification settings are unavailable") from exc
    return {"enabled": enabled, "preferred_hour": request.preferred_hour}


@app.post("/v1/notifications/run")
async def run_due_notifications(
    x_orbita_cron_token: str = Header(default="", alias="X-Orbita-Cron-Token"),
) -> dict:
    bot_token = os.getenv("ORBITA_BOT_TOKEN", "")
    supabase_url, supabase_secret_key = _supabase_settings()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram integration is not configured")
    try:
        return await dispatch_due_notifications(
            cron_token=x_orbita_cron_token,
            supabase_url=supabase_url,
            supabase_secret_key=supabase_secret_key,
            bot_token=bot_token,
            web_app_url=os.getenv(
                "ORBITA_WEB_APP_URL",
                "https://orbita-poc.vladplazmus.chatgpt.site/?startapp=daily_forecast",
            ),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Invalid scheduler token") from exc
    except (NotificationStorageError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail="Notification delivery is unavailable") from exc


@app.post("/v1/notifications/test")
async def test_notification(request: TelegramRequest) -> dict:
    identity = _telegram_identity(request.init_data)
    supabase_url, supabase_secret_key = _supabase_settings()
    bot_token = os.getenv("ORBITA_BOT_TOKEN", "")
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram integration is not configured")
    try:
        return await send_test_notification(
            supabase_url=supabase_url,
            supabase_secret_key=supabase_secret_key,
            user_key=identity.user_key,
            bot_token=bot_token,
            web_app_url=os.getenv(
                "ORBITA_WEB_APP_URL",
                "https://orbita-poc.vladplazmus.chatgpt.site/?startapp=daily_forecast",
            ),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Test delivery is not allowed") from exc
    except NotificationTestCooldownError as exc:
        raise HTTPException(status_code=429, detail="Wait before sending another test") from exc
    except NotificationStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
def natal_chart(request: NatalChartRequest, forecast_date: date | None = None) -> dict:
    try:
        chart = calculate_natal_chart(
            birth_datetime=request.birth_datetime,
            timezone_name=request.timezone,
            latitude=request.latitude,
            longitude=request.longitude,
            house_system=request.house_system,
        )
        chart["interpretation"] = interpret_natal_chart(chart)
        zone = ZoneInfo(request.timezone)
        forecast_moment = datetime.combine(forecast_date, time(hour=12), tzinfo=zone) if forecast_date else datetime.now(zone)
        chart["daily_forecast"] = calculate_daily_forecast(chart, forecast_moment)
        return chart
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
