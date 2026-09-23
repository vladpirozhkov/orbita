"""Daily Telegram forecast subscriptions and delivery."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .analytics import TelegramAnalyticsIdentity
from .astrology import calculate_daily_forecast, calculate_natal_chart


class NotificationStorageError(RuntimeError):
    """Raised when notification settings cannot be read or persisted."""


def _supabase_headers(secret_key: str, *, prefer: str | None = None) -> dict[str, str]:
    headers = {"apikey": secret_key, "Content-Type": "application/json"}
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def notification_status(
    *,
    supabase_url: str,
    supabase_secret_key: str,
    user_key: str,
) -> bool:
    url = (
        supabase_url.rstrip("/")
        + "/rest/v1/notification_subscriptions"
        + f"?select=enabled&user_key=eq.{user_key}&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(url, headers=_supabase_headers(supabase_secret_key))
            response.raise_for_status()
            rows = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise NotificationStorageError("Notification settings are unavailable") from exc
    return bool(rows and rows[0].get("enabled"))


async def save_notification_subscription(
    *,
    supabase_url: str,
    supabase_secret_key: str,
    identity: TelegramAnalyticsIdentity,
    profile: dict[str, Any] | None,
    enabled: bool,
) -> bool:
    base_url = supabase_url.rstrip("/") + "/rest/v1/notification_subscriptions"
    headers = _supabase_headers(
        supabase_secret_key,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            if not enabled:
                response = await client.delete(
                    f"{base_url}?user_key=eq.{identity.user_key}",
                    headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                )
                response.raise_for_status()
                return False

            assert profile is not None
            row = {
                "user_key": identity.user_key,
                "telegram_chat_id": identity.telegram_user_id,
                "enabled": True,
                "timezone": profile["timezone"],
                "birth_date": profile["birth_date"],
                "birth_time": profile["birth_time"],
                "latitude": profile["latitude"],
                "longitude": profile["longitude"],
                "preferred_hour": profile.get("preferred_hour", 9),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
            response = await client.post(
                f"{base_url}?on_conflict=user_key",
                headers=headers,
                json=row,
            )
            response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise NotificationStorageError("Notification settings are unavailable") from exc
    return True


async def _valid_cron_token(
    *,
    token: str,
    supabase_url: str,
    supabase_secret_key: str,
) -> bool:
    if not token:
        return False
    url = (
        supabase_url.rstrip("/")
        + "/rest/v1/notification_dispatch_config"
        + "?select=value_hash&key=eq.cron_secret_sha256&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(url, headers=_supabase_headers(supabase_secret_key))
            response.raise_for_status()
            rows = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    expected = str(rows[0].get("value_hash", "")) if rows else ""
    actual = hashlib.sha256(token.encode()).hexdigest()
    return bool(expected) and hmac.compare_digest(actual, expected)


def _notification_text(forecast: dict[str, Any]) -> str:
    scores = forecast["scores"]
    best_key = max(scores, key=scores.get)
    weak_key = min(scores, key=scores.get)
    favorable = forecast["spheres"][best_key]["favorable"]
    avoid = forecast["spheres"][weak_key]["avoid"]
    return (
        f"{forecast['headline']}. "
        f"Сегодня стоит сделать акцент на том, чтобы {favorable}; "
        f"лучше избегать следующего: {avoid}."
    )


async def dispatch_due_notifications(
    *,
    cron_token: str,
    supabase_url: str,
    supabase_secret_key: str,
    bot_token: str,
    web_app_url: str,
) -> dict[str, int]:
    if not await _valid_cron_token(
        token=cron_token,
        supabase_url=supabase_url,
        supabase_secret_key=supabase_secret_key,
    ):
        raise PermissionError("Invalid scheduler token")

    base_url = supabase_url.rstrip("/") + "/rest/v1/notification_subscriptions"
    query = (
        "?select=user_key,telegram_chat_id,timezone,birth_date,birth_time,latitude,"
        "longitude,preferred_hour,last_sent_local_date&enabled=eq.true"
    )
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(base_url + query, headers=_supabase_headers(supabase_secret_key))
        response.raise_for_status()
        subscriptions = response.json()

    now_utc = datetime.now(tz=ZoneInfo("UTC"))
    due: list[tuple[dict[str, Any], datetime]] = []
    for row in subscriptions:
        try:
            local_now = now_utc.astimezone(ZoneInfo(row["timezone"]))
        except (KeyError, ZoneInfoNotFoundError):
            continue
        if local_now.hour != int(row.get("preferred_hour", 9)):
            continue
        if row.get("last_sent_local_date") == local_now.date().isoformat():
            continue
        due.append((row, local_now))

    semaphore = asyncio.Semaphore(8)

    async def send_one(row: dict[str, Any], local_now: datetime) -> str:
        async with semaphore:
            try:
                birth_datetime = datetime.fromisoformat(
                    f"{row['birth_date']}T{row['birth_time']}"
                )
                chart = calculate_natal_chart(
                    birth_datetime=birth_datetime,
                    timezone_name=row["timezone"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    house_system="P",
                )
                forecast = calculate_daily_forecast(chart, local_now)
                payload = {
                    "chat_id": row["telegram_chat_id"],
                    "text": _notification_text(forecast),
                    "reply_markup": {
                        "inline_keyboard": [[{
                            "text": "Открыть полный прогноз",
                            "web_app": {"url": web_app_url},
                        }]],
                    },
                }
                async with httpx.AsyncClient(timeout=12.0) as client:
                    sent = await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json=payload,
                    )
                    if sent.status_code == 403:
                        await client.patch(
                            f"{base_url}?user_key=eq.{row['user_key']}",
                            headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                            json={"enabled": False, "updated_at": datetime.utcnow().isoformat() + "Z"},
                        )
                        return "disabled"
                    sent.raise_for_status()
                    updated = await client.patch(
                        f"{base_url}?user_key=eq.{row['user_key']}",
                        headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                        json={
                            "last_sent_local_date": local_now.date().isoformat(),
                            "last_sent_at": datetime.utcnow().isoformat() + "Z",
                            "updated_at": datetime.utcnow().isoformat() + "Z",
                        },
                    )
                    updated.raise_for_status()
                return "sent"
            except (KeyError, TypeError, ValueError, httpx.HTTPError, ZoneInfoNotFoundError):
                return "failed"

    results = await asyncio.gather(*(send_one(row, local_now) for row, local_now in due))
    return {
        "checked": len(subscriptions),
        "due": len(due),
        "sent": results.count("sent"),
        "failed": results.count("failed"),
        "disabled": results.count("disabled"),
    }
