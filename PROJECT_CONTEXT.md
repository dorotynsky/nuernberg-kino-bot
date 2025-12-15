# Meisengeige Bot - Project Context

## Project Goal
Create a script that runs via GitHub Actions to monitor updates to the Meisengeige cinema program at Cinecitta (https://www.cinecitta.de/programm/meisengeige/) and send notifications to a Telegram bot when updates are detected.

## Current Status
- Telegram bot has been created ✓
- Development environment configured (Python 3.14.2) ✓
- GitHub repository connected (https://github.com/dorotynsky/meisengeige-bot) ✓
- Project structure created ✓
- Core modules implemented ✓
- **Current work:** Testing the implementation

## Chosen Approach
**HTML Scraping Method** (Updated after analysis)
- Parse HTML structure from the Meisengeige page
- Extract film data from list items with class `filmapi-container__list--li`
- Extract showtime tables with dates, times, rooms, and language info
- Compare with previous snapshot to detect changes
- Future: Add filters (language, genre, time, FSK rating, etc.)

## Page Structure (Analyzed)
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

## Technical Stack
- **Python**: 3.14.2
- **Package Manager**: Poetry
- **Version Manager**: mise
- **Dependencies**:
  - httpx - for HTTP requests
  - beautifulsoup4 & lxml - for HTML parsing
  - python-telegram-bot - for Telegram integration
  - pytest, black, ruff - for development and testing

## Current Task
Configuring Python 3.14.2 in the development environment. PyCharm currently shows Python 3.10 instead of 3.14.2.

## Configuration Files
- `.mise.toml` - mise configuration (Python 3.14.2)
- `.python-version` - Python version file (3.14.2)
- `pyproject.toml` - Poetry configuration (Python ^3.14)

## Communication Guidelines
- Chat communication: Russian
- Code, commits, messages: English only
- Work step-by-step with user confirmation between steps
- **IMPORTANT**: Do NOT add Claude Code attribution or Co-Authored-By lines to commit messages
