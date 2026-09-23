from app.places import search_cities


def test_search_cities_supports_cyrillic_and_returns_timezone():
    result = search_cities("Пермь")

    assert result
    assert result[0]["label"].startswith("Пермь")
    assert result[0]["timezone"] == "Asia/Yekaterinburg"


def test_search_cities_ranks_the_largest_exact_match_first():
    result = search_cities("Madrid")

    assert result[0]["label"] == "Madrid, Spain"
    assert result[0]["timezone"] == "Europe/Madrid"
