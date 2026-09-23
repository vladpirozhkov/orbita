from app.notifications import _notification_text


def test_notification_text_is_short_and_non_technical():
    forecast = {
        "headline": "День для спокойного движения вперёд",
        "scores": {"relationships": 7, "work": 8, "energy": 4},
        "spheres": {
            "relationships": {"favorable": "обсудить важное", "avoid": "давить на близких"},
            "work": {"favorable": "закончить одну важную задачу", "avoid": "браться за всё сразу"},
            "energy": {"favorable": "снизить темп", "avoid": "работать через усталость"},
        },
    }

    text = _notification_text(forecast)

    assert text.count(".") == 2
    assert "закончить одну важную задачу" in text
    assert "работать через усталость" in text
    assert "Луна" not in text
    assert "транзит" not in text.lower()
