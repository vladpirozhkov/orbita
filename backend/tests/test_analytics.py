import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.analytics import InvalidTelegramData, sanitize_metadata, validate_telegram_init_data


BOT_TOKEN = "123456789:test-token"
NOW = 1_800_000_000


def signed_init_data(**overrides):
    values = {
        "auth_date": str(NOW - 30),
        "query_id": "AAExample",
        "start_param": "daily_forecast",
        "user": json.dumps({
            "id": 42424242,
            "first_name": "Test",
            "language_code": "ru",
            "is_premium": True,
        }, separators=(",", ":"), ensure_ascii=False),
        **overrides,
    }
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_telegram_data_becomes_stable_pseudonymous_identity():
    first = validate_telegram_init_data(signed_init_data(), BOT_TOKEN, now=NOW)
    second = validate_telegram_init_data(signed_init_data(), BOT_TOKEN, now=NOW)

    assert first.user_key == second.user_key
    assert len(first.user_key) == 64
    assert first.language_code == "ru"
    assert first.is_premium is True
    assert first.start_param == "daily_forecast"


def test_modified_telegram_data_is_rejected():
    init_data = signed_init_data().replace("daily_forecast", "other_source")

    with pytest.raises(InvalidTelegramData, match="signature"):
        validate_telegram_init_data(init_data, BOT_TOKEN, now=NOW)


def test_expired_telegram_data_is_rejected():
    with pytest.raises(InvalidTelegramData, match="expired"):
        validate_telegram_init_data(
            signed_init_data(auth_date=str(NOW - 90_000)),
            BOT_TOKEN,
            now=NOW,
        )


def test_metadata_drops_sensitive_or_unknown_values():
    result = sanitize_metadata({
        "view": "today",
        "query_length": 8,
        "birthdate": "1990-01-01",
        "dream_text": "private",
        "source": "x" * 100,
        "nested": {"unsafe": True},
    })

    assert result == {"view": "today", "query_length": 8, "source": "x" * 80}
