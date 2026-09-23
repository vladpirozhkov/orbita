from datetime import datetime
from zoneinfo import ZoneInfo

from app.notifications import _next_send_at, _notification_text


def test_notification_text_is_short_and_non_technical():
    forecast = {
        "headline": "День для спокойного движения вперёд",
        "scores": {"relationships": 7, "work": 8, "energy": 4},
        "spheres": {
            "relationships": {"level": "mid"},
            "work": {"level": "high"},
            "energy": {"level": "low"},
        },
        "daily_context": {"focus": "режим, работа и забота о себе"},
        "key_transit": {"tone": -1},
    }

    text = _notification_text(forecast)

    assert text.startswith("Привет! <b>Тебе сегодня лучше не спешить")
    assert "</b> Уже подготовили твой подробный прогноз на сегодня ✨" in text
    assert text.endswith("Зайди в приложение, чтобы узнать, чего ожидать от сегодняшнего дня!")
    assert len(text) < 300
    assert "Луна" not in text
    assert "транзит" not in text.lower()
    assert "сделать акцент на том, чтобы" not in text


def test_next_send_at_uses_the_subscribers_local_hour():
    before = datetime(2026, 9, 23, 3, 0, tzinfo=ZoneInfo("UTC"))
    after = datetime(2026, 9, 23, 5, 0, tzinfo=ZoneInfo("UTC"))

    assert _next_send_at("Asia/Yekaterinburg", 9, before) == datetime(
        2026, 9, 23, 4, 0, tzinfo=ZoneInfo("UTC")
    )
    assert _next_send_at("Asia/Yekaterinburg", 9, after) == datetime(
        2026, 9, 24, 4, 0, tzinfo=ZoneInfo("UTC")
    )
