"""Daily Telegram forecast subscriptions and delivery."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .analytics import TelegramAnalyticsIdentity
from .astrology import calculate_daily_forecast, calculate_natal_chart


class NotificationStorageError(RuntimeError):
    """Raised when notification settings cannot be read or persisted."""


class NotificationTestCooldownError(RuntimeError):
    """Raised when an admin requests test delivery too frequently."""


class TelegramDeliveryError(RuntimeError):
    """A Telegram delivery failed and may be retried."""

    def __init__(self, message: str, *, retry_after: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.permanent = permanent


def _supabase_headers(secret_key: str, *, prefer: str | None = None) -> dict[str, str]:
    headers = {"apikey": secret_key, "Content-Type": "application/json"}
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _next_send_at(timezone_name: str, preferred_hour: int, now_utc: datetime | None = None) -> datetime:
    zone = ZoneInfo(timezone_name)
    reference = now_utc or datetime.now(tz=ZoneInfo("UTC"))
    local_now = reference.astimezone(zone)
    local_date = local_now.date()
    candidate = datetime.combine(local_date, time(hour=preferred_hour), tzinfo=zone)
    if candidate <= local_now:
        candidate = datetime.combine(local_date + timedelta(days=1), time(hour=preferred_hour), tzinfo=zone)
    return candidate.astimezone(ZoneInfo("UTC"))


async def notification_status(
    *,
    supabase_url: str,
    supabase_secret_key: str,
    user_key: str,
) -> dict[str, Any]:
    subscription_url = (
        supabase_url.rstrip("/")
        + "/rest/v1/notification_subscriptions"
        + f"?select=enabled,preferred_hour&user_key=eq.{user_key}&limit=1"
    )
    admin_url = (
        supabase_url.rstrip("/")
        + "/rest/v1/notification_test_admins"
        + f"?select=user_key&user_key=eq.{user_key}&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            subscription_response, admin_response = await asyncio.gather(
                client.get(subscription_url, headers=_supabase_headers(supabase_secret_key)),
                client.get(admin_url, headers=_supabase_headers(supabase_secret_key)),
            )
            subscription_response.raise_for_status()
            admin_response.raise_for_status()
            rows = subscription_response.json()
            is_test_admin = bool(admin_response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise NotificationStorageError("Notification settings are unavailable") from exc
    if not rows:
        return {"enabled": False, "preferred_hour": 9, "can_test": is_test_admin}
    return {
        "enabled": bool(rows[0].get("enabled")),
        "preferred_hour": int(rows[0].get("preferred_hour", 9)),
        "can_test": is_test_admin,
    }


async def send_test_notification(
    *,
    supabase_url: str,
    supabase_secret_key: str,
    user_key: str,
    bot_token: str,
    web_app_url: str,
) -> dict[str, bool]:
    """Immediately send an allowlisted admin's forecast without consuming daily delivery."""

    root = supabase_url.rstrip("/") + "/rest/v1"
    headers = _supabase_headers(supabase_secret_key)
    admin_url = (
        root
        + "/notification_test_admins"
        + f"?select=user_key,last_test_sent_at&user_key=eq.{user_key}&limit=1"
    )
    subscription_url = (
        root
        + "/notification_subscriptions"
        + "?select=user_key,telegram_chat_id,timezone,birth_date,birth_time,latitude,longitude"
        + f"&user_key=eq.{user_key}&enabled=eq.true&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            admin_response, subscription_response = await asyncio.gather(
                client.get(admin_url, headers=headers),
                client.get(subscription_url, headers=headers),
            )
            admin_response.raise_for_status()
            subscription_response.raise_for_status()
            admins = admin_response.json()
            subscriptions = subscription_response.json()
            if not admins:
                raise PermissionError("Test delivery is not allowed")
            if not subscriptions:
                raise NotificationStorageError("Enable daily forecasts before testing")

            now_utc = datetime.now(tz=ZoneInfo("UTC"))
            last_sent_raw = admins[0].get("last_test_sent_at")
            if last_sent_raw:
                last_sent = datetime.fromisoformat(str(last_sent_raw).replace("Z", "+00:00"))
                if now_utc - last_sent < timedelta(seconds=30):
                    raise NotificationTestCooldownError("Wait before sending another test")

            row = subscriptions[0]
            local_now = now_utc.astimezone(ZoneInfo(row["timezone"]))
            birth_datetime = datetime.fromisoformat(f"{row['birth_date']}T{row['birth_time']}")
            chart = calculate_natal_chart(
                birth_datetime=birth_datetime,
                timezone_name=row["timezone"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                house_system="P",
            )
            forecast = calculate_daily_forecast(chart, local_now)
            sent = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": row["telegram_chat_id"],
                    "text": _notification_text(forecast),
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [[{
                            "text": "Открыть полный прогноз",
                            "web_app": {"url": web_app_url},
                        }]],
                    },
                },
            )
            sent.raise_for_status()
            marked = await client.patch(
                root + f"/notification_test_admins?user_key=eq.{user_key}",
                headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                json={"last_test_sent_at": now_utc.isoformat()},
            )
            marked.raise_for_status()
    except (PermissionError, NotificationStorageError, NotificationTestCooldownError):
        raise
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError, httpx.HTTPError) as exc:
        raise NotificationStorageError("Test delivery is unavailable") from exc
    return {"sent": True}


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
                "next_send_at": _next_send_at(
                    profile["timezone"],
                    int(profile.get("preferred_hour", 9)),
                ).isoformat(),
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


def _daily_orientation(forecast: dict[str, Any]) -> str:
    tone = int(forecast.get("key_transit", {}).get("tone", 0))
    if tone > 0:
        return "Тебе сегодня стоит заметить удачную возможность и закрепить её конкретным действием."
    if tone < 0:
        return "Тебе сегодня лучше не спешить с ответами и окончательными решениями: реакции могут быть острее обычного."
    return "Тебе сегодня лучше сохранять ровный темп и не требовать от себя резкого прорыва."


def _notification_text(forecast: dict[str, Any]) -> str:
    orientation = _daily_orientation(forecast)
    return (
        f"Привет! <b>{orientation}</b> Уже подготовили твой подробный прогноз на сегодня ✨\n\n"
        "Зайди в приложение, чтобы узнать, чего ожидать от сегодняшнего дня!"
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

    root = supabase_url.rstrip("/") + "/rest/v1"
    headers = _supabase_headers(supabase_secret_key)
    dispatch_limit = max(1, min(int(os.getenv("NOTIFICATION_DISPATCH_LIMIT", "5000")), 5000))
    batch_size = max(1, min(int(os.getenv("NOTIFICATION_BATCH_SIZE", "100")), 100))
    rate_per_second = max(1, min(int(os.getenv("TELEGRAM_MESSAGES_PER_SECOND", "20")), 25))

    class RateLimiter:
        def __init__(self, rate: int):
            self.interval = 1 / rate
            self.next_slot = 0.0
            self.lock = asyncio.Lock()

        async def wait(self) -> None:
            async with self.lock:
                loop = asyncio.get_running_loop()
                delay = self.next_slot - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.next_slot = loop.time() + self.interval

    limiter = RateLimiter(rate_per_second)
    counts = {"queued": 0, "claimed": 0, "sent": 0, "retry": 0, "failed": 0, "disabled": 0}

    async with httpx.AsyncClient(timeout=15.0) as client:
        enqueued = await client.post(
            f"{root}/rpc/enqueue_due_notification_deliveries",
            headers=headers,
            json={"p_limit": dispatch_limit},
        )
        enqueued.raise_for_status()
        counts["queued"] = int(enqueued.json() or 0)

        async def mark_delivery(
            delivery_id: int,
            *,
            status: str,
            error: str | None = None,
            retry_after: int | None = None,
        ) -> None:
            now = datetime.now(tz=ZoneInfo("UTC"))
            payload: dict[str, Any] = {
                "status": status,
                "locked_until": None,
                "last_error": error[:500] if error else None,
                "updated_at": now.isoformat(),
            }
            if status == "sent":
                payload["sent_at"] = now.isoformat()
            if status == "retry":
                payload["next_attempt_at"] = (now + timedelta(seconds=retry_after or 900)).isoformat()
            response = await client.patch(
                f"{root}/notification_deliveries?id=eq.{delivery_id}",
                headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                json=payload,
            )
            response.raise_for_status()

        async def send_one(row: dict[str, Any]) -> str:
            attempts = int(row["attempts"])
            try:
                zone = ZoneInfo(row["timezone"])
                local_date = date.fromisoformat(row["local_date"])
                forecast_moment = datetime.combine(local_date, time(hour=12), tzinfo=zone)
                birth_datetime = datetime.fromisoformat(f"{row['birth_date']}T{row['birth_time']}")
                chart = calculate_natal_chart(
                    birth_datetime=birth_datetime,
                    timezone_name=row["timezone"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    house_system="P",
                )
                forecast = calculate_daily_forecast(chart, forecast_moment)
                await limiter.wait()
                sent = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": row["telegram_chat_id"],
                        "text": _notification_text(forecast),
                        "parse_mode": "HTML",
                        "reply_markup": {
                            "inline_keyboard": [[{
                                "text": "Открыть полный прогноз",
                                "web_app": {"url": web_app_url},
                            }]],
                        },
                    },
                )
                if sent.status_code == 403:
                    raise TelegramDeliveryError("Bot was blocked by the user", permanent=True)
                if sent.status_code == 429:
                    try:
                        retry_after = int(sent.json().get("parameters", {}).get("retry_after", 60))
                    except (TypeError, ValueError):
                        retry_after = 60
                    raise TelegramDeliveryError("Telegram rate limit", retry_after=retry_after)
                if 400 <= sent.status_code < 500:
                    raise TelegramDeliveryError(f"Telegram rejected message ({sent.status_code})", permanent=True)
                sent.raise_for_status()
                now = datetime.now(tz=ZoneInfo("UTC"))
                await mark_delivery(int(row["delivery_id"]), status="sent")
                updated = await client.patch(
                    f"{root}/notification_subscriptions?user_key=eq.{row['user_key']}",
                    headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                    json={
                        "last_sent_local_date": row["local_date"],
                        "last_sent_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    },
                )
                try:
                    updated.raise_for_status()
                except httpx.HTTPError:
                    # The durable delivery row is authoritative; a failed legacy
                    # timestamp update must not cause a duplicate Telegram message.
                    pass
                return "sent"
            except TelegramDeliveryError as exc:
                if exc.permanent:
                    status = "cancelled" if "blocked" in str(exc).lower() else "failed"
                    await mark_delivery(int(row["delivery_id"]), status=status, error=str(exc))
                    if status == "cancelled":
                        disabled = await client.patch(
                            f"{root}/notification_subscriptions?user_key=eq.{row['user_key']}",
                            headers=_supabase_headers(supabase_secret_key, prefer="return=minimal"),
                            json={"enabled": False, "updated_at": datetime.now(tz=ZoneInfo('UTC')).isoformat()},
                        )
                        disabled.raise_for_status()
                        return "disabled"
                    return "failed"
                retry_after = exc.retry_after or min(3600, 60 * (5 ** max(0, attempts - 1)))
                status = "failed" if attempts >= 5 else "retry"
                await mark_delivery(int(row["delivery_id"]), status=status, error=str(exc), retry_after=retry_after)
                return status
            except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError, httpx.HTTPError) as exc:
                status = "failed" if attempts >= 5 else "retry"
                retry_after = min(3600, 60 * (5 ** max(0, attempts - 1)))
                await mark_delivery(
                    int(row["delivery_id"]),
                    status=status,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_after=retry_after,
                )
                return status

        while counts["claimed"] < dispatch_limit:
            claim = await client.post(
                f"{root}/rpc/claim_notification_deliveries",
                headers=headers,
                json={"p_limit": min(batch_size, dispatch_limit - counts["claimed"])},
            )
            claim.raise_for_status()
            deliveries = claim.json()
            if not deliveries:
                break
            counts["claimed"] += len(deliveries)
            results = await asyncio.gather(*(send_one(row) for row in deliveries))
            for result in results:
                counts[result] += 1

    return counts
