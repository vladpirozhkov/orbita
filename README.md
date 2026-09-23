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
- `backend/app/main.py` — FastAPI и расчётные endpoints;
- `backend/app/places.py` — локальный поиск города и часового пояса по снимку GeoNames;
- `backend/Dockerfile` — контейнер для публикации расчётного API.

Перед публикацией укажите адрес API в `dist/config.js`, а origin интерфейса —
в переменной `ORBITA_ALLOWED_ORIGINS` backend-сервиса. Поиск городов работает
локально и не отправляет пользовательские запросы внешнему геокодеру.

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

## Аналитика пользователей

Mini App отправляет на backend только события из фиксированного списка. Backend
проверяет подпись `Telegram.WebApp.initData`, преобразует Telegram ID в
необратимый псевдоним и записывает события в Supabase. Даты рождения, места,
имена, тексты снов и содержимое прогнозов не передаются.

Для Render-сервиса API задайте переменные:

```text
ORBITA_BOT_TOKEN=<токен @orbita_natal_bot>
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS=86400
NOTIFICATION_DISPATCH_LIMIT=5000
NOTIFICATION_BATCH_SIZE=100
TELEGRAM_MESSAGES_PER_SECOND=20
```

Секретный ключ Supabase и токен бота должны находиться только в переменных
backend-сервиса. Их нельзя добавлять в frontend, GitHub или `dist/config.js`.

Ежедневные сообщения сначала попадают в сохраняемую очередь Supabase. Временные
ошибки Telegram повторяются до пяти раз с увеличивающимся интервалом, а скорость
отправки ограничена безопасным значением. Сырые аналитические события хранятся
90 дней и автоматически очищаются ежедневным заданием базы данных.

Сводка DAU, WAU, MAU, новых пользователей, сессий и запусков доступна в
Supabase SQL Editor:

```sql
select *
from public.analytics_daily_metrics
order by metric_date desc
limit 30;
```

События по функциям приложения:

```sql
select event_name, count(*) as events, count(distinct user_key) as users
from public.analytics_events
where occurred_at >= now() - interval '30 days'
group by event_name
order by users desc, events desc;
```

## Лицензия

Проект распространяется под AGPL-3.0-or-later. Приложение использует
`pyswisseph`, которое включает Swiss Ephemeris и также распространяется под
AGPL-3.0. Секреты, ключи доступа и пользовательские данные не входят в исходный
код и никогда не должны коммититься.
