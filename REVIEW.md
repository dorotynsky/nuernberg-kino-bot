# Code Review Findings

## Баги / потенциальные ошибки

| # | Описание | Статус |
|---|----------|--------|
| 1 | Мёртвый код poster_url в `handle_films_list` | ❌ N/A (ложное: poster_url используется в `handle_film_details_callback`) |
| 2 | Хардкод русских строк вместо `get_text()` | ✅ DONE |
| 3 | `BOT_VERSION` устарел ("1.1.0" → "1.2.0") | ✅ DONE |
| 4 | O(n²) поиск фильма по индексу в callback `film_` | ✅ DONE |
| 5 | Kinderkino scraper в webhook дублирует `src/filmhaus_scraper.py` | ➡️ см. #12 (архитектурный) |
| 6 | Meisengeige scraper в webhook дублирует `src/scraper.py` | ➡️ см. #12 (архитектурный) |
| 7 | Кэш фильмов привязан к инстансу Vercel (глобальные переменные) | ⏭️ WONTFIX (ожидаемое поведение serverless, кэш — best-effort оптимизация) |
| 8 | `send_photo` fallback не передаёт `parse_mode` | ❌ N/A (ложное: fallback уже имеет `parse_mode='HTML'`) |
| 9 | Callback `back_to_films` может упасть при пустом кэше | ❌ N/A (ложное: пустой кэш перезагружается, пустой список обрабатывается) |
| 10 | Нет таймаута на HTTP-запросы к кинотеатрам в webhook | ❌ N/A (ложное: таймаут 30s уже задан) |

## Архитектурные / структурные

| # | Описание | Статус |
|---|----------|--------|
| 11 | `src/subscribers.py` — мёртвый код | ✅ DONE (удалён) |
| 12 | Дублирование кода скрейперов между `src/` и `api/webhook.py` | ⏭️ DEFERRED (рискованно: Vercel может не видеть `src/`, нужен отдельный тест) |
| 13 | `webhook.py` — 1680+ строк, сложно поддерживать | ⏭️ DEFERRED (связано с #12, нужен тест импорта `src/` на Vercel) |
| 14 | Три менеджера MongoDB с одинаковым lazy init паттерном | ✅ DONE (вынесен `BaseMongoManager`) |
| 15 | `CINEMA_SOURCES` dict дублирует данные скрейперов | ⏭️ DEFERRED (связано с #12) |
| 16 | `source_registry.py` не используется в webhook | ⏭️ DEFERRED (связано с #12) |
| 17 | Нет типизации для callback data (строковые паттерны) | ✅ DONE (добавлена валидация source_id в callback handlers) |
| 18 | Translations dict не валидируется на полноту ключей | ⏭️ WONTFIX (over-engineering для 3 языков) |

## Безопасность / надёжность

| # | Описание | Статус |
|---|----------|--------|
| 19 | `ADMIN_CHAT_ID` сравнивается как строка | ❌ N/A (ложное: сравнивается как int) |
| 20 | Нет rate limiting на команды | ⏭️ WONTFIX (Telegram API уже имеет rate limiting, stateless Vercel не позволяет) |
| 21 | MongoDB URI может попасть в traceback | ✅ DONE (обёрнуто в try/except с generic ConnectionError) |

## Стиль

| # | Описание | Статус |
|---|----------|--------|
| 22 | `print("[DEBUG]")` вместо `logging` | ✅ DONE (заменено на `logging` module) |
| 23 | Неконсистентные имена переменных | ✅ DONE (исправлен `id` → `cid`, остальные консистентны) |
| 24 | Magic numbers без именованных констант | ✅ DONE (`MAX_DESCRIPTION_LENGTH` вынесена) |
