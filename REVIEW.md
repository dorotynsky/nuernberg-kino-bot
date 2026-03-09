# Code Review Findings

## Баги / потенциальные ошибки

| # | Описание | Статус |
|---|----------|--------|
| 1 | Мёртвый код poster_url в `handle_films_list` | ❌ N/A (ложное) |
| 2 | Хардкод русских строк вместо `get_text()` | ✅ DONE |
| 3 | `BOT_VERSION` устарел ("1.1.0" → "1.2.0") | ✅ DONE |
| 4 | O(n²) поиск фильма по индексу в callback `film_` | ✅ DONE |
| 5 | Kinderkino scraper в webhook дублирует `src/filmhaus_scraper.py` | ✅ DONE (см. #12) |
| 6 | Meisengeige scraper в webhook дублирует `src/scraper.py` | ✅ DONE (см. #12) |
| 7 | Кэш фильмов привязан к инстансу Vercel (глобальные переменные) | ⏭️ WONTFIX (ожидаемое поведение serverless) |
| 8 | `send_photo` fallback не передаёт `parse_mode` | ❌ N/A (ложное) |
| 9 | Callback `back_to_films` может упасть при пустом кэше | ❌ N/A (ложное) |
| 10 | Нет таймаута на HTTP-запросы к кинотеатрам в webhook | ❌ N/A (ложное) |

## Архитектурные / структурные

| # | Описание | Статус |
|---|----------|--------|
| 11 | `src/subscribers.py` — мёртвый код | ✅ DONE (удалён) |
| 12 | Дублирование кода скрейперов между `src/` и `api/webhook.py` | ✅ DONE (webhook импортирует из `src/`, удалено ~380 строк) |
| 13 | `webhook.py` — 1680+ строк, сложно поддерживать | ✅ DONE (сокращён до ~1300 строк) |
| 14 | Три менеджера MongoDB с одинаковым lazy init паттерном | ✅ DONE (вынесен `BaseMongoManager`) |
| 15 | `CINEMA_SOURCES` dict дублирует данные скрейперов | ⏭️ WONTFIX (dict нужен для переведённых display_name) |
| 16 | `source_registry.py` не используется в webhook | ⏭️ WONTFIX (webhook использует CINEMA_SOURCES для UI) |
| 17 | Нет типизации для callback data (строковые паттерны) | ✅ DONE (добавлена валидация source_id) |
| 18 | Translations dict не валидируется на полноту ключей | ⏭️ WONTFIX (over-engineering для 3 языков) |

## Безопасность / надёжность

| # | Описание | Статус |
|---|----------|--------|
| 19 | `ADMIN_CHAT_ID` сравнивается как строка | ❌ N/A (ложное) |
| 20 | Нет rate limiting на команды | ⏭️ WONTFIX (Telegram API имеет rate limiting) |
| 21 | MongoDB URI может попасть в traceback | ✅ DONE |

## Стиль

| # | Описание | Статус |
|---|----------|--------|
| 22 | `print("[DEBUG]")` вместо `logging` | ✅ DONE |
| 23 | Неконсистентные имена переменных | ✅ DONE |
| 24 | Magic numbers без именованных констант | ✅ DONE |
