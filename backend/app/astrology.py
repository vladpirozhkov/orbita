"""Deterministic natal-chart calculations backed by Swiss Ephemeris.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

import swisseph as swe

SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
    "True Node": swe.TRUE_NODE,
}

ASPECTS = {
    "conjunction": (0.0, 8.0),
    "sextile": (60.0, 4.0),
    "square": (90.0, 6.0),
    "trine": (120.0, 6.0),
    "opposition": (180.0, 8.0),
}

SIGN_TEXT = {
    "Aries": ("прямота, инициатива и смелость начинать", "действовать раньше, чем появляется полная ясность"),
    "Taurus": ("устойчивость, практичность и верность ценностям", "слишком долго держаться за привычное"),
    "Gemini": ("любознательность, гибкость и лёгкость в общении", "распылять внимание между множеством идей"),
    "Cancer": ("эмоциональная глубина, забота и сильная память", "закрываться, когда особенно нужна поддержка"),
    "Leo": ("творческая смелость, щедрость и яркое самовыражение", "зависеть от признания окружающих"),
    "Virgo": ("наблюдательность, системность и внимание к деталям", "быть чрезмерно критичным к себе"),
    "Libra": ("дипломатичность, чувство меры и умение видеть обе стороны", "откладывать выбор ради сохранения гармонии"),
    "Scorpio": ("проницательность, внутренняя сила и способность к трансформации", "усиливать контроль при нехватке доверия"),
    "Sagittarius": ("широта взгляда, оптимизм и стремление к смыслу", "переоценивать возможности и недооценивать детали"),
    "Capricorn": ("ответственность, выдержка и умение строить надолго", "мерить собственную ценность только результатами"),
    "Aquarius": ("независимое мышление, оригинальность и ориентация на будущее", "уходить в дистанцию вместо разговора о чувствах"),
    "Pisces": ("эмпатия, воображение и тонкое восприятие", "терять границы под влиянием эмоций других людей"),
}

SIGN_RU = dict(zip(SIGNS, ("Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева", "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы")))
PLANET_RU = {"Sun": "Солнце", "Moon": "Луна", "Mercury": "Меркурий", "Venus": "Венера", "Mars": "Марс", "Jupiter": "Юпитер", "Saturn": "Сатурн", "Uranus": "Уран", "Neptune": "Нептун", "Pluto": "Плутон", "True Node": "Северный узел"}
HOUSE_TEXT = {
    1: "самопрезентация, тело и личная инициатива", 2: "ценности, деньги и чувство опоры",
    3: "общение, обучение и близкое окружение", 4: "дом, семья и внутреннее чувство безопасности",
    5: "творчество, романтика и удовольствие", 6: "повседневность, навыки и забота о себе",
    7: "партнёрство, договорённости и отражение себя в другом", 8: "доверие, близость и глубокие перемены",
    9: "мировоззрение, путешествия и поиск смысла", 10: "карьера, статус и долгосрочные цели",
    11: "друзья, сообщества и образ будущего", 12: "уединение, бессознательное и восстановление",
}

ASPECT_TONE = {
    "conjunction": (0, "усиливает"),
    "sextile": (1, "открывает возможность для"),
    "trine": (1, "поддерживает"),
    "square": (-1, "создаёт напряжение в теме"),
    "opposition": (-1, "просит найти баланс в теме"),
}


@dataclass(frozen=True)
class Position:
    longitude: float
    latitude: float
    speed: float
    sign: str
    degree_in_sign: float
    retrograde: bool


def _position(values: tuple[float, ...]) -> Position:
    longitude = values[0] % 360
    return Position(
        longitude=round(longitude, 6),
        latitude=round(values[1], 6),
        speed=round(values[3], 6),
        sign=SIGNS[int(longitude // 30)],
        degree_in_sign=round(longitude % 30, 6),
        retrograde=values[3] < 0,
    )


def _utc_julian_day(local_dt: datetime, timezone_name: str) -> tuple[float, str]:
    if local_dt.tzinfo is not None:
        raise ValueError("birth_datetime must not contain an offset")
    zone = ZoneInfo(timezone_name)
    utc_dt = local_dt.replace(tzinfo=zone).astimezone(timezone.utc)
    hour = utc_dt.hour + utc_dt.minute / 60 + utc_dt.second / 3600
    return swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour, swe.GREG_CAL), utc_dt.isoformat()


def _angular_distance(a: float, b: float) -> float:
    distance = abs(a - b) % 360
    return min(distance, 360 - distance)


def _house_for(longitude: float, cusps: tuple[float, ...]) -> int:
    normalized = longitude % 360
    for index, start in enumerate(cusps):
        end = cusps[(index + 1) % 12]
        if (normalized - start) % 360 < (end - start) % 360:
            return index + 1
    return 12


def calculate_natal_chart(
    birth_datetime: datetime,
    timezone_name: str,
    latitude: float,
    longitude: float,
    house_system: str = "P",
) -> dict:
    """Calculate planets, Placidus house cusps, angles and major aspects."""
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    if len(house_system) != 1:
        raise ValueError("house_system must be a one-character Swiss Ephemeris code")

    jd_ut, utc_datetime = _utc_julian_day(birth_datetime, timezone_name)
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    positions: dict[str, Position] = {}

    for name, body in PLANETS.items():
        values, _ = swe.calc_ut(jd_ut, body, flags)
        positions[name] = _position(values)

    cusps, angles = swe.houses_ex(jd_ut, latitude, longitude, house_system.encode())
    houses = [
        {
            "number": index + 1,
            "longitude": round(value % 360, 6),
            "sign": SIGNS[int((value % 360) // 30)],
            "degree_in_sign": round(value % 30, 6),
        }
        for index, value in enumerate(cusps)
    ]

    aspect_rows = []
    for (left_name, left), (right_name, right) in combinations(positions.items(), 2):
        separation = _angular_distance(left.longitude, right.longitude)
        for aspect_name, (exact, max_orb) in ASPECTS.items():
            orb = abs(separation - exact)
            if orb <= max_orb:
                aspect_rows.append({
                    "from": left_name,
                    "to": right_name,
                    "type": aspect_name,
                    "orb": round(orb, 4),
                })
                break

    return {
        "engine": {"name": "Swiss Ephemeris", "version": swe.version},
        "input": {
            "local_datetime": birth_datetime.isoformat(),
            "timezone": timezone_name,
            "utc_datetime": utc_datetime,
            "latitude": latitude,
            "longitude": longitude,
            "house_system": house_system,
        },
        "julian_day_ut": round(jd_ut, 8),
        "planets": {
            name: {**asdict(value), "house": _house_for(value.longitude, cusps)}
            for name, value in positions.items()
        },
        "houses": houses,
        "angles": {
            "ascendant": round(angles[0] % 360, 6),
            "midheaven": round(angles[1] % 360, 6),
            "armc": round(angles[2] % 360, 6),
            "vertex": round(angles[3] % 360, 6),
        },
        "aspects": sorted(aspect_rows, key=lambda row: row["orb"]),
    }


def interpret_natal_chart(chart: dict) -> dict:
    """Build a transparent rule-based interpretation from calculated positions."""
    sun = chart["planets"]["Sun"]
    moon = chart["planets"]["Moon"]
    asc_sign = SIGNS[int(chart["angles"]["ascendant"] // 30)]
    sun_strength, sun_risk = SIGN_TEXT[sun["sign"]]
    moon_strength, moon_risk = SIGN_TEXT[moon["sign"]]
    asc_strength, _ = SIGN_TEXT[asc_sign]
    tense = [row for row in chart["aspects"] if row["type"] in {"square", "opposition"}][:3]
    supportive = [row for row in chart["aspects"] if row["type"] in {"trine", "sextile"}][:3]
    mercury = chart["planets"]["Mercury"]
    venus = chart["planets"]["Venus"]
    mars = chart["planets"]["Mars"]
    jupiter = chart["planets"]["Jupiter"]
    saturn = chart["planets"]["Saturn"]
    cards = [
        {
            "key": "identity", "title": "Характер и самоощущение",
            "summary": f"Солнце в знаке {SIGN_RU[sun['sign']]} · {sun['house']} дом",
            "body": f"Ваш основной способ проявлять себя — {sun_strength}. Сфера, где это особенно заметно: {HOUSE_TEXT[sun['house']]}. Важно не {sun_risk}.",
        },
        {
            "key": "emotions", "title": "Эмоции и чувство безопасности",
            "summary": f"Луна в знаке {SIGN_RU[moon['sign']]} · {moon['house']} дом",
            "body": f"Для эмоционального равновесия нужны качества: {moon_strength}. Чувства особенно включаются через темы «{HOUSE_TEXT[moon['house']]}». Риск — {moon_risk}.",
        },
        {
            "key": "communication", "title": "Мышление и общение",
            "summary": f"Меркурий в знаке {SIGN_RU[mercury['sign']]} · {mercury['house']} дом",
            "body": f"Интеллектуальный стиль опирается на такие качества, как {SIGN_TEXT[mercury['sign']][0]}. Лучше всего мышление раскрывается через {HOUSE_TEXT[mercury['house']]}.",
        },
        {
            "key": "relationships", "title": "Любовь и отношения",
            "summary": f"Венера в знаке {SIGN_RU[venus['sign']]} · {venus['house']} дом",
            "body": f"В близости особенно ценятся {SIGN_TEXT[venus['sign']][0]}. Любовь и симпатия проявляются через сферу «{HOUSE_TEXT[venus['house']]}»; важно не {SIGN_TEXT[venus['sign']][1]}.",
        },
        {
            "key": "action", "title": "Воля, энергия и конфликты",
            "summary": f"Марс в знаке {SIGN_RU[mars['sign']]} · {mars['house']} дом",
            "body": f"Способ добиваться своего связан с качествами: {SIGN_TEXT[mars['sign']][0]}. Главная зона приложения энергии — {HOUSE_TEXT[mars['house']]}. Под давлением возможна тенденция {SIGN_TEXT[mars['sign']][1]}.",
        },
        {
            "key": "career", "title": "Развитие и карьера",
            "summary": f"Юпитер — {jupiter['house']} дом · Сатурн — {saturn['house']} дом",
            "body": f"Рост приходит через сферу «{HOUSE_TEXT[jupiter['house']]}», а устойчивый результат требует дисциплины в теме «{HOUSE_TEXT[saturn['house']]}». Сочетание этих зон показывает, где потенциал превращается в долгосрочную компетенцию.",
        },
        {
            "key": "growth", "title": "Ресурсы и зоны роста",
            "summary": f"{len(supportive)} поддерживающих и {len(tense)} напряжённых ключевых аспекта",
            "body": f"Гармоничные аспекты показывают навыки, которые включаются естественно. Напряжённые — не недостатки, а повторяющиеся задачи выбора. Главный ориентир: не {sun_risk}; в эмоциональных решениях — не {moon_risk}.",
        },
    ]
    return {
        "headline": f"{sun_strength.capitalize()} — ядро карты; {asc_strength} заметны во внешнем стиле.",
        "identity": (
            f"Солнце в знаке {SIGN_RU[sun['sign']]} и в {sun['house']} доме связывает чувство себя с темами "
            f"этого дома. Ваш естественный ресурс — {sun_strength}."
        ),
        "emotions": (
            f"Луна в знаке {SIGN_RU[moon['sign']]} и в {moon['house']} доме показывает эмоциональную потребность "
            f"в безопасном проявлении таких качеств, как {moon_strength}."
        ),
        "social_style": f"Асцендент в знаке {SIGN_RU[asc_sign]}: первое впечатление и способ входить в новые ситуации — {asc_strength}.",
        "growth": f"Зоны роста карты: не {sun_risk}; в эмоциональных решениях — не {moon_risk}.",
        "supportive_aspects": supportive,
        "tense_aspects": tense,
        "cards": cards,
        "method": "Rule-based interpretation of Swiss Ephemeris positions",
    }


def calculate_daily_forecast(chart: dict, forecast_date: datetime) -> dict:
    """Calculate daily transits to natal planets and turn them into a short forecast."""
    local_date = forecast_date.date()
    noon_utc = datetime(local_date.year, local_date.month, local_date.day, 12, tzinfo=timezone.utc)
    hour = noon_utc.hour
    jd_ut = swe.julday(noon_utc.year, noon_utc.month, noon_utc.day, hour, swe.GREG_CAL)
    transit_bodies = {name: body for name, body in PLANETS.items() if name in {"Sun", "Moon", "Mercury", "Venus", "Mars"}}
    transits = {}
    for name, body in transit_bodies.items():
        values, _ = swe.calc_ut(jd_ut, body, swe.FLG_SWIEPH | swe.FLG_SPEED)
        transits[name] = _position(values)

    hits = []
    for transit_name, transit in transits.items():
        for natal_name, natal in chart["planets"].items():
            separation = _angular_distance(transit.longitude, natal["longitude"])
            for aspect_name, (exact, _) in ASPECTS.items():
                orb = abs(separation - exact)
                if orb <= 2.5:
                    tone, verb = ASPECT_TONE[aspect_name]
                    hits.append({
                        "transit": transit_name,
                        "natal": natal_name,
                        "type": aspect_name,
                        "orb": round(orb, 2),
                        "tone": tone,
                        "text": f"{PLANET_RU[transit_name]} {verb} натальную тему «{PLANET_RU[natal_name]}»",
                    })
                    break
    hits.sort(key=lambda row: row["orb"])
    selected = hits[:5]
    scores = {"relationships": 6, "work": 6, "energy": 6}
    for row in selected:
        impact = row["tone"]
        if row["transit"] in {"Venus", "Moon"} or row["natal"] in {"Venus", "Moon"}:
            scores["relationships"] += impact
        if row["transit"] == "Mercury" or row["natal"] in {"Mercury", "Jupiter", "Saturn"}:
            scores["work"] += impact
        if row["transit"] in {"Sun", "Mars"} or row["natal"] in {"Sun", "Mars"}:
            scores["energy"] += impact
    scores = {key: max(1, min(10, value)) for key, value in scores.items()}
    if selected:
        supportive_count = sum(row["tone"] > 0 for row in selected)
        tense_count = sum(row["tone"] < 0 for row in selected)
        if supportive_count > tense_count:
            headline = "День для поступательного движения"
            summary = "Поддерживающие транзиты помогают использовать сильные стороны карты. Выберите одно направление и закрепите результат действием."
        elif tense_count > supportive_count:
            headline = "День требует точности и паузы"
            summary = "Напряжённые транзиты усиливают внутренние противоречия. Проверяйте факты и не превращайте первую эмоциональную реакцию в окончательное решение."
        else:
            headline = "День настройки баланса"
            summary = "В карте дня сочетаются поддержка и напряжение. Лучше чередовать активность с короткими паузами и не перегружать расписание."
    else:
        headline = "Спокойный транзитный фон"
        summary = "Точных сильных аспектов к натальной карте сегодня немного. Это хороший день для привычных задач и восстановления ресурса."
    return {
        "date": local_date.isoformat(),
        "headline": headline,
        "summary": summary,
        "scores": scores,
        "transits": selected,
        "method": "Swiss Ephemeris transits at 12:00 UTC, 2.5° orb",
    }
