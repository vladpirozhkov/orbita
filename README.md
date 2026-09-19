# Орбита

Открытый персональный астрологический ассистент для Telegram: натальная карта,
транзиты, матрица судьбы, совместимость и дневник снов.

## Статус

Интерфейс является интерактивным PoC. В каталоге `backend` находится первый
реальный расчётный модуль: натальная карта на базе Swiss Ephemeris. AI не
рассчитывает положения планет и не изменяет полученные числа.

## Запуск расчётного API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload
```

Документация API будет доступна по адресу `http://127.0.0.1:8000/docs`.

Пример запроса:

```json
{
  "birth_datetime": "1996-02-10T23:50:00",
  "timezone": "Asia/Yekaterinburg",
  "latitude": 58.0105,
  "longitude": 56.2502,
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

