# Claude Project Knowledge - Nürnberg Kino Bot

This file provides Claude with essential context about the Nürnberg Kino Bot project for optimal assistance in new sessions.

## Quick Project Summary

**Nürnberg Kino Bot** is a production Telegram bot that monitors cinema programs in Nuremberg, Germany. It tracks two cinema sources (Meisengeige at Cinecitta and Kinderkino at Filmhaus) and sends notifications to subscribers about new films, updated showtimes, and removed films.

## Tech Stack
- **Language**: Python 3.12+ (3.14.2 for local development)
- **Package Manager**: Poetry
- **Deployment**: Vercel (webhook) + GitHub Actions (monitoring)
- **Database**: MongoDB Atlas
- **Bot Framework**: python-telegram-bot
- **Web Scraping**: httpx + BeautifulSoup4

## Repository Structure
```
├── api/webhook.py              # Telegram bot webhook (Vercel serverless)
├── src/                        # Core application code
│   ├── base_scraper.py         # Base scraper interface
│   ├── scraper.py              # Meisengeige scraper
│   ├── filmhaus_scraper.py     # Kinderkino scraper
│   ├── source_registry.py      # Source management
│   ├── models.py               # Data models
│   ├── storage.py              # Snapshot storage
│   ├── subscribers.py          # Subscription management
│   ├── notifier.py             # Telegram notifications
│   └── main.py                 # Monitoring script entry
├── .github/workflows/monitor.yml  # Daily monitoring cron
├── ARCHITECTURE.md             # Detailed technical docs
├── DEVELOPMENT.md              # Developer guide
├── PROJECT_CONTEXT.md          # Project overview
└── README.md                   # Quick start
```

## Key Files to Reference

### For Understanding Architecture
- `ARCHITECTURE.md` - Complete system design and data flow
- `PROJECT_CONTEXT.md` - Current status and features
- `api/webhook.py` - Main bot logic (single file, ~1600 lines)

### For Development Tasks
- `DEVELOPMENT.md` - Setup, workflows, common tasks
- `src/base_scraper.py` - Scraper interface pattern
- `src/source_registry.py` - How sources are managed

### For Scraping Logic
- `src/scraper.py` - Meisengeige HTML parsing
- `src/filmhaus_scraper.py` - Kinderkino with detail fetching

## Important Concepts

### Multi-Source Architecture
- **Source Registry Pattern**: Scrapers register themselves
- **Per-Source Subscriptions**: Users subscribe independently to each cinema
- **Per-Source Caching**: 5-minute TTL per source in webhook
- **Per-Source Snapshots**: Separate snapshot files in GitHub Actions cache

### Multi-Language Support
- Three languages: Russian (ru), German (de), English (en)
- User preferences stored in MongoDB
- Per-user command menu via `BotCommandScopeChat`
- All UI text translated via `TRANSLATIONS` dictionary

### Deployment Architecture
1. **Webhook** (Vercel): Handles bot commands, user interactions
2. **Monitoring** (GitHub Actions): Daily scraping and notifications
3. **Database** (MongoDB Atlas): User subscriptions and preferences

## Common Development Patterns

### Adding a New Command
1. Create handler function: `async def handle_new_command(bot, chat_id)`
2. Add routing in `process_update()`: `elif text == '/new': ...`
3. Add to command menu in `get_commands_for_language()`
4. Add translations in `TRANSLATIONS` dict

### Adding a New Cinema Source
1. Create scraper class extending `BaseCinemaScraper`
2. Register in source registry: `source_registry.register_source(NewScraper)`
3. Add to `CINEMA_SOURCES` dict in webhook.py
4. No other changes needed (automatic integration)

### Code Locations for Common Tasks

**Bot Commands**: `api/webhook.py` → `process_update()` function
**Callback Handlers**: `api/webhook.py` → callback query section
**Translations**: `api/webhook.py` → `TRANSLATIONS` dict
**Scraping Logic**: `src/scraper.py` and `src/filmhaus_scraper.py`
**MongoDB Schema**: `api/webhook.py` → Manager classes
**Monitoring Script**: `src/main.py` → `main()` function

## Database Schema

**Database Name**: `nuernberg_kino_bot`

**Collections**:
1. `subscribers`: User subscriptions
   ```json
   {
     "chat_id": 123456,
     "sources": ["meisengeige", "kinderkino"],
     "language": "ru"
   }
   ```

2. `languages`: Language preferences (separate for compatibility)
   ```json
   {
     "chat_id": 123456,
     "language": "ru"
   }
   ```

3. `user_versions`: Bot version tracking
   ```json
   {
     "chat_id": 123456,
     "version": "1.1.0"
   }
   ```

## Environment Variables

**Required**:
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `MONGODB_URI` - MongoDB Atlas connection string

**Optional**:
- `ADMIN_CHAT_ID` - For /broadcast command access

## Key Design Decisions

### Why Single-File Webhook?
- Vercel serverless function works best with single entry point
- Reduces cold start time (lazy MongoDB init, no connections at import)
- All bot logic contained in `api/webhook.py`

### Why Separate Monitoring Script?
- GitHub Actions has better cron reliability than Vercel cron
- Can run longer than serverless timeout (10s default)
- State persistence via GitHub Actions cache

### Why MongoDB?
- User data needs to persist across deployments
- Vercel is stateless (no local storage)
- MongoDB Atlas free tier sufficient

### Why Per-Source Subscriptions?
- Users want different notifications (kids movies vs art house)
- Allows future expansion to more cinemas
- More flexible than all-or-nothing subscription

## Codebase Conventions

### Naming
- Scrapers: `{Cinema}Scraper` (e.g., `MeisengeigeScraper`)
- Handlers: `handle_{command}_command()` (e.g., `handle_films_command()`)
- Callbacks: `{action}_callback()` or inline in `process_update()`
- Models: PascalCase dataclasses (e.g., `Film`, `Showtime`)

### File Organization
- Main bot logic: `api/webhook.py` (single file)
- Scrapers: `src/{source}_scraper.py`
- Shared code: `src/` directory
- Tests: `tests/` directory

### Error Handling
- Graceful degradation (show error message, don't crash)
- Log errors for debugging
- Continue processing other items on failure

## Testing Strategy

### Manual Testing
- Use `/start` to test language selection
- Use `/films` to test source selection and scraping
- Use `/sources` to test subscription management
- Use `/language` to test command menu updates

### Automated Testing
- Unit tests for scrapers (HTML parsing)
- Integration tests for bot commands (mock Telegram API)
- End-to-end tests for monitoring script

## Current Status (v1.2.0)

**Production**: ✅ Fully deployed and operational

**Features**:
- ✅ Multi-source monitoring (2 cinemas)
- ✅ Multi-language support (3 languages)
- ✅ Rich film information with detail scraping
- ✅ Per-user command menu
- ✅ Interactive inline keyboards
- ✅ Daily notifications via GitHub Actions (subscribers from MongoDB)
- ✅ Persistent storage with MongoDB
- ✅ Lazy MongoDB init to prevent Vercel cold start timeout
- ✅ Daily MongoDB keep-alive ping (prevents Atlas free tier pause)

**Known Limitations**:
- Kinderkino detail fetching adds latency (~1-2s per film)
- Vercel free tier has execution time limits (10s)
- GitHub Actions cache has 7-day retention
- MongoDB Atlas free tier pauses after 60 days of inactivity (mitigated by daily ping)
- Telegram photo caption limit is 1024 chars (descriptions truncated to 600 chars)

## Communication Style

**With User (in Russian)**:
- Code discussions in English
- Commit messages in English
- User-facing text translated to ru/de/en

**Code Standards**:
- Conventional commits
- Google-style docstrings
- Black formatting (100 char line length)
- Type hints where helpful (not strict)

## Useful Commands

```bash
# Run monitoring locally
poetry run python -m src.main

# Test scrapers
poetry run python -c "from src.scraper import MeisengeigeScraper; ..."

# Run bot in polling mode (local testing)
poetry run python -m src.run_bot

# Format code
poetry run black .

# Lint code
poetry run ruff check .
```

## Recent Major Changes

1. **Fixed webhook and notifications** (Mar 2026)
   - Lazy MongoDB init: shared singleton, no connections at module load
   - Monitoring now reads subscribers from MongoDB (was file-based)
   - Daily MongoDB keep-alive ping prevents Atlas free tier pause
   - Film detail descriptions truncated to 600 chars (Telegram caption limit)

2. **Renamed from Meisengeige Bot** (Dec 2024)
   - Updated all references to "Nürnberg Kino Bot"
   - New MongoDB database: `nuernberg_kino_bot`
   - Updated repository name on GitHub

3. **Added Kinderkino Detail Scraping** (Dec 2024)
   - Fetches detail pages for full film info
   - Extracts FSK, duration, director, full description

4. **Fixed Command Menu Language** (Dec 2024)
   - Now uses per-user command scope
   - Updates immediately on language change

## Links

- **Repository**: https://github.com/dorotynsky/nuernberg-kino-bot
- **Deployment**: Vercel (auto-deploy from main)
- **Monitoring**: GitHub Actions (daily at 9:10 AM UTC / 10:10 CET winter)
- **Meisengeige Program**: https://www.cinecitta.de/programm/meisengeige/
- **Kinderkino Program**: https://www.kunstkulturquartier.de/filmhaus/programm/kinderkino
