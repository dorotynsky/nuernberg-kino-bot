# Development Guide - Nürnberg Kino Bot

## Prerequisites

- **Python**: 3.12+ (3.14.2 recommended for local development)
- **Poetry**: Package manager for Python dependencies
- **mise**: Version manager (optional but recommended)
- **MongoDB**: Local instance or MongoDB Atlas account
- **Telegram Bot Token**: From [@BotFather](https://t.me/botfather)

## Initial Setup

### 1. Clone Repository

```bash
git clone git@github.com:dorotynsky/nuernberg-kino-bot.git
cd nuernberg-kino-bot
```

### 2. Install Python with mise (Recommended)

```bash
mise install
```

This will install Python 3.14.2 as specified in `.mise.toml`.

### 3. Install Dependencies

```bash
poetry install
```

This installs all dependencies including dev tools (pytest, black, ruff).

### 4. Configure Environment Variables

Create `.env` file in project root:

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/

# Optional
ADMIN_CHAT_ID=your_telegram_user_id  # For /broadcast command
```

**Note**: `.env` is in `.gitignore` - never commit secrets!

## Project Structure

```
nuernberg-kino-bot/
├── api/
│   └── webhook.py           # Vercel serverless function (Telegram bot)
├── src/
│   ├── base_scraper.py      # Base scraper interface
│   ├── scraper.py           # Meisengeige scraper
│   ├── filmhaus_scraper.py  # Kinderkino scraper
│   ├── source_registry.py   # Source registry pattern
│   ├── models.py            # Data models (Film, Showtime, etc.)
│   ├── storage.py           # Snapshot storage
│   ├── subscribers.py       # Subscriber management
│   ├── notifier.py          # Telegram notifications
│   ├── main.py              # Monitoring script entry point
│   └── run_bot.py           # Local bot runner (polling mode)
├── .github/workflows/
│   └── monitor.yml          # Daily monitoring workflow
├── tests/                   # Unit tests
├── ARCHITECTURE.md          # Technical architecture
├── DEVELOPMENT.md           # This file
├── PROJECT_CONTEXT.md       # Project overview
├── README.md                # Quick start guide
├── pyproject.toml           # Poetry configuration
├── .mise.toml               # mise configuration
└── .python-version          # Python version specification
```

## Development Workflows

### Running the Monitoring Script Locally

Test cinema scraping and notification logic:

```bash
# Run with notifications enabled
poetry run python -m src.main

# Dry run (no notifications)
# Modify src/main.py to pass notify=False
```

This will:
1. Scrape both cinema sources
2. Compare with cached snapshots
3. Send notifications to subscribed users (if notify=True)
4. Save new snapshots

### Running the Bot Locally (Polling Mode)

Test bot commands without webhook:

```bash
poetry run python -m src.run_bot
```

This starts the bot in polling mode. You can interact with it in Telegram.

**Note**: Don't run this while Vercel webhook is active (they'll conflict).

### Testing Individual Components

#### Test Meisengeige Scraper

```python
poetry run python -c "
from src.scraper import MeisengeigeScraper

with MeisengeigeScraper() as scraper:
    films = scraper.scrape()
    print(f'Found {len(films)} films')
    for film in films[:3]:
        print(f'- {film.title}')
"
```

#### Test Kinderkino Scraper

```python
poetry run python -c "
from src.filmhaus_scraper import FilmhausScraper

with FilmhausScraper() as scraper:
    films = scraper.scrape()
    print(f'Found {len(films)} films')
    for film in films[:3]:
        print(f'- {film.title}')
        print(f'  FSK: {film.fsk_rating}, Duration: {film.duration}min')
"
```

#### Test MongoDB Connection

```python
poetry run python -c "
import os
from pymongo import MongoClient

uri = os.getenv('MONGODB_URI')
client = MongoClient(uri)
db = client['nuernberg_kino_bot']
count = db['subscribers'].count_documents({})
print(f'Total subscribers: {count}')
"
```

## Code Quality

### Formatting with Black

```bash
poetry run black src/ api/ tests/
```

Configuration in `pyproject.toml`:
- Line length: 100
- Target version: Python 3.14

### Linting with Ruff

```bash
poetry run ruff check src/ api/ tests/
```

Configuration in `pyproject.toml`:
- Line length: 100
- Target version: Python 3.14

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src --cov=api

# Run specific test file
poetry run pytest tests/test_scraper.py
```

## Git Workflow

### Branch Strategy

- `main`: Production branch (auto-deploys to Vercel)
- Feature branches: `feature/description`
- Bug fixes: `fix/description`

### Commit Message Format

Use conventional commits:

```
feat: Add Kinderkino detail page scraping
fix: Command menu language not updating
docs: Update architecture documentation
refactor: Extract source registry pattern
test: Add unit tests for FilmhausScraper
```

### Before Committing

1. **Format code**: `poetry run black .`
2. **Lint code**: `poetry run ruff check .`
3. **Run tests**: `poetry run pytest`
4. **Check types** (if using mypy): `poetry run mypy src/`

## Deployment

### Vercel (Webhook)

**Automatic Deployment**:
- Push to `main` branch triggers auto-deploy
- Vercel builds and deploys `api/webhook.py`

**Manual Deployment**:
```bash
vercel deploy --prod
```

**Environment Variables**:
Set in Vercel dashboard:
- `TELEGRAM_BOT_TOKEN`
- `MONGODB_URI`
- `ADMIN_CHAT_ID` (optional)

### GitHub Actions (Monitoring)

**Automatic Execution**:
- Runs daily at 9:00 AM UTC
- Configured in `.github/workflows/monitor.yml`

**Manual Trigger**:
1. Go to Actions tab in GitHub
2. Select "Monitor Cinema Programs" workflow
3. Click "Run workflow"

**Secrets Configuration**:
Set in GitHub repo settings:
- `TELEGRAM_BOT_TOKEN`
- `MONGODB_URI`

## Common Development Tasks

### Adding a New Cinema Source

1. **Create scraper class**:
```python
# src/new_cinema_scraper.py
from src.base_scraper import BaseCinemaScraper
from src.models import Film

class NewCinemaScraper(BaseCinemaScraper):
    BASE_URL = "https://example.com/program"

    def get_source_id(self) -> str:
        return "newcinema"

    def get_display_name(self) -> str:
        return "New Cinema"

    def get_url(self) -> str:
        return self.BASE_URL

    def scrape(self) -> List[Film]:
        # Implementation
        pass
```

2. **Register in source registry** (`src/main.py`):
```python
from src.new_cinema_scraper import NewCinemaScraper

source_registry.register_source(NewCinemaScraper)
```

3. **Add to webhook** (`api/webhook.py`):
```python
CINEMA_SOURCES = {
    'meisengeige': {...},
    'kinderkino': {...},
    'newcinema': {  # Add this
        'id': 'newcinema',
        'display_name': 'New Cinema',
        'display_name_ru': 'Новый Кинотеатр',
        'display_name_de': 'Neues Kino',
        'display_name_en': 'New Cinema',
        'url': 'https://example.com/program'
    }
}
```

4. **Test the scraper**:
```bash
poetry run python -c "
from src.new_cinema_scraper import NewCinemaScraper
scraper = NewCinemaScraper()
films = scraper.scrape()
print(f'Found {len(films)} films')
"
```

### Adding a New Bot Command

1. **Add handler function** in `api/webhook.py`:
```python
async def handle_new_command(bot: Bot, chat_id: int) -> None:
    """Handle /new command."""
    # Implementation
    await bot.send_message(
        chat_id=chat_id,
        text="Response text"
    )
```

2. **Route command** in `process_update()`:
```python
elif text == '/new':
    print("[DEBUG] Routing to handle_new_command")
    await handle_new_command(bot, chat_id)
    return {'status': 'success', 'command': text}
```

3. **Add to command menu** in `get_commands_for_language()`:
```python
'ru': [
    # ...existing commands
    BotCommand("new", "📝 Новая команда")
]
```

4. **Add translations** in `TRANSLATIONS`:
```python
'ru': {
    # ...existing translations
    'new_command_text': 'Текст для новой команды'
}
```

### Adding a New Language

1. **Add translations** in `api/webhook.py`:
```python
TRANSLATIONS = {
    # ...existing languages
    'fr': {  # French
        'choose_language': '🌍 Choisir la langue',
        # ...all other keys
    }
}
```

2. **Add to language selection** in `handle_start_command()`:
```python
keyboard = [
    [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
    [InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang_de")],
    [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
    [InlineKeyboardButton("🇫🇷 Français", callback_data="lang_fr")],  # Add
]
```

3. **Add to command menu** in `get_commands_for_language()`:
```python
'fr': [
    BotCommand("films", "🎥 Afficher le programme"),
    # ...all other commands
]
```

## Troubleshooting

### Bot Not Responding

1. **Check Vercel logs**: https://vercel.com/dashboard/deployments
2. **Verify webhook**: https://api.telegram.org/bot<TOKEN>/getWebhookInfo
3. **Check MongoDB connection**: Test with connection string
4. **Verify environment variables**: Check Vercel dashboard

### Scraper Not Finding Films

1. **Test scraper directly**: Run individual scraper script
2. **Check website HTML**: Cinema may have changed structure
3. **Verify selectors**: BeautifulSoup `find()` calls may need updating
4. **Check network**: Ensure cinema website is accessible

### Notifications Not Sent

1. **Check subscriber count**: Use `/status` command
2. **Verify source subscriptions**: Check MongoDB `subscribers` collection
3. **Check GitHub Actions logs**: View workflow run results
4. **Verify bot token**: Ensure `TELEGRAM_BOT_TOKEN` is correct

### MongoDB Connection Issues

1. **Check connection string**: Verify `MONGODB_URI` format
2. **Whitelist IP**: Add Vercel IPs to MongoDB Atlas whitelist (or use 0.0.0.0/0)
3. **Test locally**: Try connecting from local machine
4. **Check credentials**: Ensure username/password are correct

## Performance Optimization Tips

### Reduce Cold Start Time
- Keep dependencies minimal
- Use single-file webhook (`api/webhook.py`)
- Avoid heavy imports at module level

### Reduce Scraping Time
- Use httpx with connection pooling
- Cache film data (5-minute TTL)
- Parallel scraping for multiple sources

### Reduce Database Queries
- Index MongoDB collections on `chat_id`
- Batch queries where possible
- Cache user preferences in memory (with TTL)

## Communication Guidelines

### Code & Commits
- **Language**: English only
- **Style**: Clear, descriptive commit messages
- **Format**: Conventional commits

### Documentation
- **Inline comments**: English only
- **Docstrings**: Google style
- **Documentation files**: English only

### User-Facing Text
- **Bot messages**: Multi-language (ru/de/en)
- **Command descriptions**: Translated per language
- **Error messages**: Translated per language

## Resources

- **Telegram Bot API**: https://core.telegram.org/bots/api
- **python-telegram-bot**: https://python-telegram-bot.readthedocs.io/
- **Vercel Functions**: https://vercel.com/docs/functions
- **MongoDB Atlas**: https://www.mongodb.com/docs/atlas/
- **Poetry**: https://python-poetry.org/docs/
- **mise**: https://mise.jdx.dev/

## Getting Help

### Issues
Report bugs and feature requests in GitHub Issues.

### Discussion
Use GitHub Discussions for questions and ideas.

### Contact
Reach project maintainer via Telegram or GitHub.
