"""Privacy-conscious analytics for the Orbita Telegram Mini App."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl

import httpx


ALLOWED_EVENT_NAMES = frozenset({
    "app_open",
    "view_opened",
    "profile_completed",
    "daily_forecast_viewed",
    "forecast_details_opened",
    "natal_chart_viewed",
    "partner_profile_saved",
    "partner_chart_viewed",
    "compatibility_viewed",
    "matrix_viewed",
    "sphere_viewed",
    "dream_saved",
    "dream_edited",
    "dream_deleted",
    "dictionary_searched",
    "daily_notification_enabled",
    "daily_notification_disabled",
    "daily_notification_opened",
})

ALLOWED_METADATA_KEYS = frozenset({
    "view",
    "source",
    "has_profile",
    "result",
    "query_length",
    "theme",
    "cached",
    "sphere",
})


class InvalidTelegramData(ValueError):
    """Raised when Telegram Mini App launch data cannot be trusted."""


class AnalyticsStorageError(RuntimeError):
    """Raised when an analytics batch cannot be persisted."""


@dataclass(frozen=True)
class TelegramAnalyticsIdentity:
    user_key: str
    language_code: str | None
    is_premium: bool | None
    start_param: str | None


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86_400,
    now: int | None = None,
) -> TelegramAnalyticsIdentity:
    """Validate Telegram WebApp initData and return a pseudonymous identity."""

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    if not pairs or len({key for key, _ in pairs}) != len(pairs):
        raise InvalidTelegramData("Invalid Telegram launch data")

    values = dict(pairs)
    received_hash = values.pop("hash", "")
    if len(received_hash) != 64:
        raise InvalidTelegramData("Telegram signature is missing")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InvalidTelegramData("Telegram signature is invalid")

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        telegram_user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidTelegramData("Telegram user data is incomplete") from exc

    current_time = int(time.time() if now is None else now)
    if auth_date > current_time + 60 or current_time - auth_date > max_age_seconds:
        raise InvalidTelegramData("Telegram launch data has expired")
    if user.get("is_bot"):
        raise InvalidTelegramData("Bots are not analytics users")

    user_key = hmac.new(
        bot_token.encode(),
        f"orbita-analytics:{telegram_user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    language_code = str(user.get("language_code", ""))[:16] or None
    is_premium = user.get("is_premium") if isinstance(user.get("is_premium"), bool) else None
    start_param = str(values.get("start_param", ""))[:64] or None
    return TelegramAnalyticsIdentity(user_key, language_code, is_premium, start_param)


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    """Keep only small, non-sensitive product metadata."""

    sanitized: dict[str, str | int | float | bool | None] = {}
    for key, value in metadata.items():
        if key not in ALLOWED_METADATA_KEYS or not isinstance(value, (str, int, float, bool, type(None))):
            continue
        sanitized[key] = value[:80] if isinstance(value, str) else value
    return sanitized


async def store_analytics_batch(
    *,
    supabase_url: str,
    supabase_secret_key: str,
    identity: TelegramAnalyticsIdentity,
    events: list[dict[str, Any]],
    platform: str | None,
    app_version: str | None,
) -> int:
    """Persist a validated, idempotent event batch through the Supabase Data API."""

    base_url = supabase_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": supabase_secret_key,
        "Content-Type": "application/json",
    }
    if not supabase_secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {supabase_secret_key}"
    user_row = {
        "user_key": identity.user_key,
        "last_platform": platform,
        "language_code": identity.language_code,
        "is_premium": identity.is_premium,
        "first_start_param": identity.start_param,
        "last_start_param": identity.start_param,
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    update_row = {
        "last_seen_at": now_iso,
        "last_platform": platform,
        "language_code": identity.language_code,
        "is_premium": identity.is_premium,
        "last_start_param": identity.start_param,
    }
    event_rows = [{
        "event_id": str(event["event_id"]),
        "user_key": identity.user_key,
        "event_name": event["name"],
        "session_id": str(event["session_id"]),
        "client_occurred_at": event.get("occurred_at"),
        "platform": platform,
        "app_version": app_version,
        "metadata": sanitize_metadata(event.get("metadata") or {}),
    } for event in events]

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            create_response = await client.post(
                f"{base_url}/analytics_users?on_conflict=user_key",
                headers={**headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                json=user_row,
            )
            create_response.raise_for_status()
            update_response = await client.patch(
                f"{base_url}/analytics_users?user_key=eq.{identity.user_key}",
                headers={**headers, "Prefer": "return=minimal"},
                json=update_row,
            )
            update_response.raise_for_status()
            events_response = await client.post(
                f"{base_url}/analytics_events?on_conflict=event_id",
                headers={**headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                json=event_rows,
            )
            events_response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AnalyticsStorageError("Analytics storage is unavailable") from exc
    return len(event_rows)
