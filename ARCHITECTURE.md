# Architecture - Nürnberg Kino Bot

## System Overview

**Nürnberg Kino Bot** is a Telegram bot that monitors cinema programs in Nuremberg and notifies subscribers about updates. The system consists of three main components:

1. **Telegram Bot Webhook** (Vercel serverless function)
2. **Monitoring Script** (GitHub Actions cron job)
3. **MongoDB Database** (MongoDB Atlas)

## Component Architecture

```
┌─────────────────┐
│  Telegram API   │
└────────┬────────┘
         │ Webhook
         ▼
┌─────────────────────────────────┐
│   Vercel Serverless Function    │
│   (api/webhook.py)               │
│                                  │
│  - Handles bot commands          │
│  - Manages subscriptions         │
│  - Updates user preferences      │
│  - Multi-language support        │
└──────────┬──────────────────────┘
           │ Read/Write
           ▼
┌─────────────────────────────────┐
│   MongoDB Atlas                  │
│   (nuernberg_kino_bot)           │
│                                  │
│  Collections:                    │
│  - subscribers (per-source)      │
│  - languages (user preferences)  │
│  - user_versions (for updates)   │
└──────────────────────────────────┘

┌─────────────────────────────────┐
│   GitHub Actions                 │
│   (Daily at 9:10 AM UTC)         │
│                                  │
│  1. Scrape cinema websites       │
│  2. Compare with cached state    │
│  3. Detect changes               │
│  4. Send notifications           │
└──────────┬──────────────────────┘
           │ HTTP Requests
           ▼
┌─────────────────────────────────┐
│   Cinema Websites                │
│   - Cinecitta (Meisengeige)      │
│   - Filmhaus (Kinderkino)        │
└──────────────────────────────────┘
```

## Data Flow

### User Interaction Flow
1. User sends command to bot (e.g., `/films`)
2. Telegram sends webhook POST to Vercel
3. Webhook processes command via `process_update()`
4. Command handler executes (e.g., `handle_films_command()`)
5. Data fetched from MongoDB or cinema websites
6. Response sent back to user via Telegram API

### Monitoring Flow
1. GitHub Actions triggers daily at 9:10 AM UTC
2. For each cinema source:
   - Fetch current program from website
   - Load previous snapshot from cache
   - Compare to detect changes
   - Send notifications to subscribed users (from MongoDB)
   - Save new snapshot to cache
3. Cache persisted via GitHub Actions cache
4. MongoDB keep-alive ping to prevent Atlas free tier pause

## Core Components

### 1. Web Scraping System

#### Base Scraper (`src/base_scraper.py`)
Abstract base class defining scraper interface:
```python
class BaseCinemaScraper(ABC):
    @abstractmethod
    def get_source_id(self) -> str
    @abstractmethod
    def get_display_name(self) -> str
    @abstractmethod
    def get_url(self) -> str
    @abstractmethod
    def scrape(self) -> List[Film]
```

#### Source Registry (`src/source_registry.py`)
Centralized registry for managing cinema sources:
- Registers scrapers dynamically
- Provides factory methods for creating scraper instances
- Maps source IDs to scraper implementations

#### Scrapers
- **MeisengeigeScraper** (`src/scraper.py`): Parses Cinecitta's Meisengeige program
- **FilmhausScraper** (`src/filmhaus_scraper.py`): Parses Filmhaus Kinderkino program
  - Fetches main listing page
  - Follows detail page links for each film
  - Extracts rich metadata (FSK, duration, director, etc.)

### 2. Telegram Bot (Webhook)

#### Location
`api/webhook.py` - Single-file serverless function for Vercel

#### Key Classes
- **SubscriberManager**: Manages user subscriptions in MongoDB
- **LanguageManager**: Stores and retrieves user language preferences
- **UserVersionManager**: Tracks bot version per user for update notifications

#### Command Handlers
- `handle_start_command()`: Language selection and subscription
- `handle_films_command()`: Shows source selection for viewing programs
- `handle_films_list()`: Displays film list for selected source
- `handle_sources_command()`: Manages source subscriptions
- `handle_status_command()`: Shows user's active subscriptions
- `handle_language_command()`: Changes language and updates command menu

#### Callback Handlers
Processes inline keyboard button clicks:
- `lang_*`: Language selection
- `changelang_*`: Language change
- `films_source:*`: View films from specific source
- `film_*`: View film details
- `sub:*`: Subscribe to source
- `unsub:*`: Unsubscribe from source
- `back_to_*`: Navigation

### 3. Data Models (`src/models.py`)

```python
@dataclass
class Showtime:
    date: str        # e.g., "Mo.22.12"
    time: str        # e.g., "15:00"
    room: str        # e.g., "Kino 2"
    language: str    # e.g., "OV", "OmU"

@dataclass
class Film:
    title: str
    genres: List[str]
    fsk_rating: Optional[str]
    duration: Optional[int]
    description: Optional[str]
    poster_url: Optional[str]
    film_id: Optional[str]
    showtimes: List[Showtime]

@dataclass
class ProgramSnapshot:
    timestamp: str
    films: List[Film]
    source_id: str
```

### 4. Storage System

#### GitHub Actions Cache
- Per-source snapshot files: `{source_id}_snapshot.json`
- Persisted between workflow runs
- 7-day retention

#### MongoDB Collections

**Database**: `nuernberg_kino_bot`

**subscribers** - User subscriptions
```json
{
  "_id": ObjectId,
  "chat_id": 123456,
  "sources": ["meisengeige", "kinderkino"],
  "language": "ru"
}
```

**languages** - Language preferences
```json
{
  "_id": ObjectId,
  "chat_id": 123456,
  "language": "ru"
}
```

**user_versions** - Version tracking
```json
{
  "_id": ObjectId,
  "chat_id": 123456,
  "version": "1.1.0"
}
```

## Multi-Language Support

### Language Management
- Three supported languages: Russian (ru), German (de), English (en)
- User preference stored in MongoDB
- Default language: Russian (based on Telegram client language)

### Translation System
- `TRANSLATIONS` dictionary in webhook.py with all text strings
- `get_text(chat_id, key, **kwargs)` function for retrieval
- Template string formatting with parameters

### Command Menu
- Per-user command menu set via `BotCommandScopeChat`
- Updates immediately when user changes language
- Uses `set_user_commands(bot, chat_id, lang)` function

## Caching Strategy

### Film Data Cache (Webhook)
- 5-minute TTL per source
- Stored in global variables (per Vercel instance)
- Cache key format: `{source_id}_cache`
- Reduces load on cinema websites

### Snapshot Cache (GitHub Actions)
- Persistent between workflow runs
- Uses GitHub Actions cache API
- Separate file per source
- Enables change detection

## Security Considerations

### Environment Variables
- `TELEGRAM_BOT_TOKEN`: Never logged or exposed
- `MONGODB_URI`: Connection string with credentials
- `ADMIN_CHAT_ID`: Optional, for broadcast command

### Input Validation
- All user input sanitized
- Callback data validated against expected patterns
- MongoDB queries use parameterized inputs

### Rate Limiting
- Telegram Bot API has built-in rate limits
- Vercel has execution time limits (10s default)
- Cinema website scraping throttled via caching

## Error Handling

### Webhook Errors
- Try-catch blocks around all command handlers
- Graceful degradation (fallback messages)
- Logging to Vercel console

### Scraping Errors
- Individual film parsing failures don't stop entire scrape
- Network errors caught and logged
- Fallback to cached data when available

### MongoDB Errors
- Connection failures logged
- Operations wrapped in try-catch
- Graceful fallback (e.g., assume no subscription if DB unavailable)

## Performance Optimization

### Webhook Performance
- Single-file deployment reduces cold start time
- Lazy MongoDB initialization (shared singleton, connects on first request)
- Caching reduces external API calls

### Scraping Performance
- Parallel scraping of multiple sources in monitoring script
- Detail page fetching only for Kinderkino (where needed)
- Efficient HTML parsing with BeautifulSoup

### MongoDB Optimization
- Shared singleton MongoClient with lazy initialization
- serverSelectionTimeoutMS=5000 to fail fast on connection issues
- Minimal data per document
- Efficient queries (find by chat_id)

## Deployment

### Vercel (Webhook)
- Serverless function in `api/webhook.py`
- Auto-deploys on git push to main
- Environment variables configured in Vercel dashboard
- Custom domain support (optional)

### GitHub Actions (Monitoring)
- Workflow in `.github/workflows/monitor.yml`
- Scheduled: Daily at 9:10 AM UTC (10:10 CET winter time)
- Manual trigger: `workflow_dispatch`
- Secrets: `TELEGRAM_BOT_TOKEN`, `MONGODB_URI`, `TELEGRAM_CHAT_ID`

## Monitoring & Observability

### Logs
- Vercel: Function logs in dashboard
- GitHub Actions: Workflow run logs
- MongoDB: Atlas monitoring

### Metrics
- Subscriber count per source
- Film count per source
- Scraping success/failure rate (visible in logs)

## Future Extensibility

### Adding New Cinema Sources
1. Create new scraper class extending `BaseCinemaScraper`
2. Register in source registry
3. Add to `CINEMA_SOURCES` in webhook.py
4. No other changes needed (automatic integration)

### Adding New Languages
1. Add language code to `TRANSLATIONS` dictionary
2. Translate all keys
3. Add to language selection keyboard
4. Add to `get_commands_for_language()` function

### Adding New Features
- Bot commands: Add handler and route in `process_update()`
- Callback actions: Add handler in callback query section
- Data fields: Extend `Film` or `Showtime` dataclass
