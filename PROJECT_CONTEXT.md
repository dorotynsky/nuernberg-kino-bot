# Nürnberg Kino Bot - Project Context

## Project Goal
Monitor cinema programs in Nuremberg (Meisengeige at Cinecitta and Kinderkino at Filmhaus) and provide notifications to subscribers via Telegram bot with multi-language support.

## Current Status
- ✅ Multi-source cinema monitoring (Meisengeige + Kinderkino)
- ✅ Independent per-source subscriptions with MongoDB storage
- ✅ Multi-language support (Russian, German, English)
- ✅ Interactive bot commands with inline keyboards
- ✅ Rich film information with detail page scraping
- ✅ User-specific command menu based on language preference
- ✅ Telegram bot webhook deployed on Vercel
- ✅ Daily monitoring via GitHub Actions
- ✅ Development environment (Python 3.14.2 locally, 3.12 in CI)
- ✅ Repository: https://github.com/dorotynsky/nuernberg-kino-bot
- **Status:** Production-ready with full feature set! 🎉🎬

## Architecture

### Deployment
- **Webhook API**: Vercel serverless function (`api/webhook.py`)
- **Monitoring Script**: GitHub Actions (daily at 9:00 AM UTC)
- **Database**: MongoDB Atlas for persistent storage
- **Bot**: Telegram Bot API with python-telegram-bot

### Multi-Source Monitoring System
- **Base scraper abstraction** with source registry pattern
- **Two scrapers implemented**:
  - **MeisengeigeScraper**: Parses Cinecitta Meisengeige program
  - **FilmhausScraper**: Parses Filmhaus Kinderkino program with detail page fetching
- **Per-source snapshot storage**: Separate JSON files via GitHub Actions cache
- **Per-source subscription management**: MongoDB with source arrays per user
- **Independent subscriptions**: Users choose Meisengeige, Kinderkino, or both
- **Rich notifications**: Film posters, descriptions, FSK ratings, showtimes

### Data Flow
1. **Monitoring** (GitHub Actions): Scrape → Compare → Notify subscribers
2. **Bot Webhook** (Vercel): Receive updates → Process commands → Update MongoDB
3. **User Interaction**: Commands → Inline keyboards → Callbacks → MongoDB updates

## Page Structures

### Meisengeige (Cinecitta)
Each film on https://www.cinecitta.de/programm/meisengeige/ contains:
- **Title**: In `<h3 class="text-white">` tag
- **Genres**: Tags like "Arthouse", "Drama", "Komödie", "Thriller", "Dokumentation"
- **FSK Rating**: Age restriction (e.g., "FSK: 16")
- **Duration**: In minutes (e.g., "119min")
- **Description**: Brief plot summary in `<p>` tag
- **Poster**: Image URL in `<img>` tag
- **Showtimes**: Table with:
  - Dates (e.g., "Mo. 15.12", "Di. 16.12")
  - Cinema room (e.g., "Kino 2")
  - Language (e.g., "OV" = original version, "OmU" = with subtitles)
  - Times (e.g., "20:30")

### Kinderkino (Filmhaus)
Each event on https://www.kunstkulturquartier.de/filmhaus/programm/kinderkino contains:
- **Title**: In `<a class="detailLink">` tag
- **Date/Time**: Format "Mo / 22.12.2025 / 15:00 Uhr"
- **Venue**: "Filmhaus Nürnberg - kinoeins"
- **Category**: "Kinderkino"
- **Poster Image**: Scene stills from films
- **Description**: Brief plot summary
- **Schedule**: Typically Fridays-Sundays at 3 PM

## Technical Stack
- **Python**: 3.14.2
- **Package Manager**: Poetry
- **Version Manager**: mise
- **Dependencies**:
  - httpx - for HTTP requests
  - beautifulsoup4 & lxml - for HTML parsing
  - python-telegram-bot - for Telegram integration
  - pytest, black, ruff - for development and testing

## Bot Commands
- `/films` - View current cinema programs with source selection
- `/sources` - Manage cinema source subscriptions (interactive buttons)
- `/start` - Subscribe to notifications (language selection on first use)
- `/status` - View active subscriptions and subscriber counts per source
- `/language` - Change bot language (updates command menu immediately)
- `/stop` - Unsubscribe from notifications

## Features
- **Multi-language**: Russian, German, English with per-user command menu
- **Source selection**: Independent subscriptions to Meisengeige and/or Kinderkino
- **Film browsing**: View programs by source with detailed information
- **Rich details**: Full descriptions, FSK ratings, duration, director (for Kinderkino)
- **Smart caching**: 5-minute cache per source to reduce API calls
- **Notifications**: Daily checks with poster images and showtime details

## Recent Changes (v1.1.0)
- ✅ Renamed to "Nürnberg Kino Bot" from "Meisengeige Bot"
- ✅ Added cinema source selection for /films command
- ✅ Implemented Kinderkino detail page scraping for rich information
- ✅ Fixed command menu language to follow user preference (not Telegram app language)
- ✅ Added multi-language support (Russian, German, English)
- ✅ Migrated to MongoDB Atlas for persistent storage
- ✅ Implemented multi-source monitoring system
- ✅ Added interactive inline keyboards for all commands

## MongoDB Collections (Database: `nuernberg_kino_bot`)
- **subscribers**: User subscriptions with source arrays
  ```json
  {
    "chat_id": 123456,
    "sources": ["meisengeige", "kinderkino"],
    "language": "ru"
  }
  ```
- **languages**: User language preferences
  ```json
  {
    "chat_id": 123456,
    "language": "ru"
  }
  ```
- **user_versions**: Track bot version for update notifications
  ```json
  {
    "chat_id": 123456,
    "version": "1.1.0"
  }
  ```

## Environment Variables
- `TELEGRAM_BOT_TOKEN` - Telegram bot token from @BotFather
- `MONGODB_URI` - MongoDB Atlas connection string
- `ADMIN_CHAT_ID` (optional) - Admin chat ID for /broadcast command

## Configuration Files
- `.mise.toml` - mise configuration (Python 3.14.2)
- `.python-version` - Python version file (3.14.2)
- `pyproject.toml` - Poetry configuration (Python ^3.14)
- `vercel.json` - Vercel deployment configuration

## Communication Guidelines
- Chat communication: Russian
- Code, commits, messages: English only
- Work step-by-step with user confirmation between steps
- **IMPORTANT**: Do NOT add Claude Code attribution or Co-Authored-By lines to commit messages
