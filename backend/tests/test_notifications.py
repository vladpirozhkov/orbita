from app.notifications import _notification_text


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
