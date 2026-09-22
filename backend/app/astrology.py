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

MOON_SIGN_DAY_TEXT = {
    "Aries": "реагировать быстрее и прямее, чем обычно",
    "Taurus": "искать устойчивость, понятный ритм и телесный комфорт",
    "Gemini": "чаще переключаться между разговорами, идеями и новостями",
    "Cancer": "острее замечать потребность в близости и безопасной обстановке",
    "Leo": "смелее показывать чувства и ждать заметного отклика",
    "Virgo": "наводить порядок и внимательнее видеть несовершенные детали",
    "Libra": "искать согласие и учитывать реакцию другого человека",
    "Scorpio": "переживать глубже и внимательнее считывать скрытые мотивы",
    "Sagittarius": "стремиться к движению, смыслу и более широкому взгляду",
    "Capricorn": "собираться вокруг обязанностей и конкретного результата",
    "Aquarius": "нуждаться в свободе выбора и свежем способе решить задачу",
    "Pisces": "тоньше воспринимать атмосферу, намёки и собственную усталость",
}

MOON_HOUSE_FOCUS = {
    1: "самочувствие и личная инициатива", 2: "деньги и чувство опоры",
    3: "разговоры и текущие дела", 4: "дом и эмоциональная безопасность",
    5: "творчество, симпатия и удовольствие", 6: "режим, работа и забота о себе",
    7: "отношения и договорённости", 8: "доверие и общие ресурсы",
    9: "обучение, планы и новые впечатления", 10: "цели и профессиональная видимость",
    11: "друзья, команды и планы на будущее", 12: "отдых, завершение и внутреннее восстановление",
}

ASPECT_TONE = {
    "conjunction": (0, "соединение"),
    "sextile": (1, "секстиль"),
    "trine": (1, "тригон"),
    "square": (-1, "квадрат"),
    "opposition": (-1, "оппозиция"),
}

TRANSIT_THEME = {
    "Sun": "уверенность, воля и проявление себя", "Moon": "эмоции, настроение и автоматические реакции",
    "Mercury": "мышление, разговоры и документы", "Venus": "симпатия, отношения и личные ценности",
    "Mars": "энергия, напор и способ действовать",
}
NATAL_THEME = {
    "Sun": "самооценка и жизненные цели", "Moon": "эмоциональная безопасность", "Mercury": "мышление и коммуникация",
    "Venus": "близость и ценности", "Mars": "воля и границы", "Jupiter": "рост и возможности",
    "Saturn": "ответственность и ограничения", "Uranus": "свобода и перемены", "Neptune": "интуиция и идеалы",
    "Pluto": "контроль и глубокая трансформация", "True Node": "долгосрочное направление развития",
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
                    tone, aspect_label = ASPECT_TONE[aspect_name]
                    hits.append({
                        "transit": transit_name,
                        "natal": natal_name,
                        "type": aspect_name,
                        "orb": round(orb, 2),
                        "tone": tone,
                        "text": f"{PLANET_RU[transit_name]} — {PLANET_RU[natal_name]}: {aspect_label}",
                    })
                    break
    hits.sort(key=lambda row: row["orb"])
    lunar_hits = [row for row in hits if row["transit"] == "Moon"]
    # A daily forecast must not be led for several days by the same slow transit.
    # Keep the most exact lunar contact in view, then fill the list by precision.
    lead_lunar = lunar_hits[0] if lunar_hits else None
    selected = ([lead_lunar] if lead_lunar else []) + [
        row for row in hits if row is not lead_lunar
    ][:4 if lead_lunar else 5]

    house_cusps = tuple(row["longitude"] for row in chart["houses"])
    transit_moon = transits["Moon"]
    moon_house = _house_for(transit_moon.longitude, house_cusps)
    moon_sign_ru = SIGN_RU[transit_moon.sign]
    moon_focus = MOON_HOUSE_FOCUS[moon_house]
    daily_context = {
        "moon_sign": transit_moon.sign,
        "moon_sign_ru": moon_sign_ru,
        "moon_degree": round(transit_moon.degree_in_sign, 1),
        "moon_house": moon_house,
        "focus": moon_focus,
        "summary": (
            f"Луна сегодня проходит {transit_moon.degree_in_sign:.1f}° знака {moon_sign_ru} "
            f"и активирует {moon_house} дом твоей натальной карты. Поэтому заметнее тема: {moon_focus}. "
            f"Эмоциональный ритм может побуждать {MOON_SIGN_DAY_TEXT[transit_moon.sign]}."
        ),
    }
    scores = {"relationships": 6, "work": 6, "energy": 6}
    for row in selected:
        impact = row["tone"]
        if row["transit"] in {"Venus", "Moon"} or row["natal"] in {"Venus", "Moon"}:
            scores["relationships"] += impact
        if row["transit"] == "Mercury" or row["natal"] in {"Mercury", "Jupiter", "Saturn"}:
            scores["work"] += impact
        if row["transit"] in {"Sun", "Mars"} or row["natal"] in {"Sun", "Mars"}:
            scores["energy"] += impact
    if moon_house in {5, 7, 8}:
        scores["relationships"] += 1
    if moon_house in {2, 3, 6, 10}:
        scores["work"] += 1
    if moon_house in {1, 5, 9, 11}:
        scores["energy"] += 1
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
    def sphere_copy(key: str, score: int) -> dict:
        copy = {
            "relationships": {
                "high": ("Легче услышать друг друга и прямо выразить симпатию.", "знакомства, тёплый разговор, совместные решения", "идеализировать обещания и торопить сближение"),
                "mid": ("Эмоциональный фон зависит от качества общения больше, чем от обстоятельств.", "спокойно уточнять ожидания и замечать реальные действия", "додумывать мотивы другого человека"),
                "low": ("Чувствительность повышена: нейтральные слова могут восприниматься острее обычного.", "обозначать чувства без обвинений и брать паузу", "ультиматумы, проверки и решения на пике эмоций"),
            },
            "work": {
                "high": ("Проще концентрироваться, договариваться и продвигать конкретный результат.", "важная задача, переговоры, планирование и завершение", "брать на себя больше, чем реально выполнить"),
                "mid": ("День подходит для последовательной работы без резких рывков.", "рутинные задачи, проверка деталей и наведение порядка", "многозадачность и постоянное переключение"),
                "low": ("Вероятны задержки, спорные формулировки или повышенная требовательность к себе.", "перепроверять документы и оставлять запас времени", "конфликтовать с руководством и обещать быстрый результат"),
            },
            "energy": {
                "high": ("Физический и волевой ресурс выше обычного — легче перейти от мысли к действию.", "спорт, активные дела и задачи, требующие инициативы", "перегружаться и игнорировать сигналы усталости"),
                "mid": ("Ресурс ровный, если не расходовать его на лишнюю спешку.", "умеренная нагрузка и привычный режим", "компенсировать усталость стимуляторами и поздней активностью"),
                "low": ("Энергия может идти волнами; восстановление сегодня продуктивнее форсирования.", "сон, прогулка, короткие задачи и снижение темпа", "интенсивные нагрузки и борьба с усталостью через силу"),
            },
        }
        level = "high" if score >= 8 else "low" if score <= 4 else "mid"
        summary, favorable, avoid = copy[key][level]
        return {"score": score, "level": level, "summary": summary, "favorable": favorable, "avoid": avoid}

    spheres = {key: sphere_copy(key, score) for key, score in scores.items()}
    top = lead_lunar or (selected[0] if selected else None)
    if top:
        aspect_effect = {
            "conjunction": "Темы двух планет усиливают друг друга и становятся заметнее.",
            "sextile": "Возникает возможность, которую важно поддержать собственным действием.",
            "trine": "Обстоятельства складываются мягче, привычные способности доступны легче.",
            "square": "Возникает внутреннее или внешнее напряжение, требующее осознанной корректировки.",
            "opposition": "Две потребности тянут в разные стороны, поэтому важно найти рабочий баланс.",
        }[top["type"]]
        practical = "Используйте паузу перед важной реакцией и выбирайте конкретный следующий шаг." if top["tone"] < 0 else "Зафиксируйте возможность конкретным действием, пока поддерживающий аспект точен."
        key_transit = {
            "title": top["text"],
            "explanation": f"Сегодня взаимодействуют {TRANSIT_THEME[top['transit']]} и {NATAL_THEME[top['natal']]}. {aspect_effect}",
            "advice": practical,
            "orb": top["orb"],
        }
    else:
        key_transit = {
            "title": "Точных сильных транзитов сегодня немного",
            "explanation": "Фон дня не требует резких изменений и позволяет опираться на привычный ритм.",
            "advice": "Сосредоточьтесь на восстановлении и завершении уже начатого.",
            "orb": None,
        }

    best_key = max(scores, key=scores.get)
    weak_key = min(scores, key=scores.get)
    sphere_names = {"relationships": "отношений", "work": "работы", "energy": "энергии"}
    overview = {
        "what_to_expect": f"{daily_context['summary']} {summary}",
        "favorable": f"Лучше всего поддержана сфера {sphere_names[best_key]}: {spheres[best_key]['favorable']}.",
        "avoid": f"Больше внимания требует сфера {sphere_names[weak_key]}. Лучше избегать: {spheres[weak_key]['avoid']}.",
    }
    return {
        "date": local_date.isoformat(),
        "headline": headline,
        "summary": summary,
        "scores": scores,
        "spheres": spheres,
        "overview": overview,
        "key_transit": key_transit,
        "daily_context": daily_context,
        "transits": selected,
        "method": "Swiss Ephemeris transits at 12:00 UTC; lunar house and major aspects within a 2.5° orb",
    }
