# Орбита

Открытый персональный астрологический ассистент для Telegram: натальная карта,
транзиты, матрица судьбы, совместимость и дневник снов.

## Статус

Интерфейс является интерактивным PoC. В каталоге `backend` находится первый
реальный расчётный модуль: натальная карта на базе Swiss Ephemeris. AI не
рассчитывает положения планет и не изменяет полученные числа.

Живой интерфейс PoC: <https://orbita-poc.vladplazmus.chatgpt.site>

## Архитектура

- `dist` — статический интерфейс Telegram Mini App;
- `backend/app/astrology.py` — детерминированный расчёт планет, домов и аспектов;
- `backend/app/main.py` — FastAPI, поиск места и определение часового пояса;
- `backend/Dockerfile` — контейнер для публикации расчётного API.

Перед публикацией укажите адрес API в `dist/config.js`, а origin интерфейса —
в переменной `ORBITA_ALLOWED_ORIGINS` backend-сервиса. Для публичного геокодера
также задайте корректный `NOMINATIM_USER_AGENT` с контактным адресом.

## Запуск расчётного API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload
```

Или через Docker:

```bash
docker build -f backend/Dockerfile -t orbita-api .
docker run --rm -p 8000:8000 --env-file .env orbita-api
```

Документация API будет доступна по адресу `http://127.0.0.1:8000/docs`.

Пример запроса:

```json
{
  "birth_datetime": "1990-01-01T12:00:00",
  "timezone": "Europe/Paris",
  "latitude": 48.8566,
  "longitude": 2.3522,
  "house_system": "P"
}
```

## Проверка

```bash
PYTHONPATH=backend pytest backend/tests
```

## Лицензия

Проект распространяется под AGPL-3.0-or-later. Приложение использует
`pyswisseph`, которое включает Swiss Ephemeris и также распространяется под
AGPL-3.0. Секреты, ключи доступа и пользовательские данные не входят в исходный
код и никогда не должны коммититься.
