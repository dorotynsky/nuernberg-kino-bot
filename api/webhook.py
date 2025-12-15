"""Vercel serverless function for Telegram webhook."""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

import httpx
from bs4 import BeautifulSoup
from telegram import Update, Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError


# Data models for films
@dataclass
class Showtime:
    """Represents a single film showtime."""
    date: str
    time: str
    room: str
    language: Optional[str] = None


@dataclass
class Film:
    """Represents a film with all its information."""
    title: str
    genres: List[str] = field(default_factory=list)
    fsk_rating: Optional[str] = None
    duration: Optional[int] = None
    description: Optional[str] = None
    poster_url: Optional[str] = None
    showtimes: List[Showtime] = field(default_factory=list)
    film_id: Optional[str] = None


# Inline SubscriberManager (copied from src/subscribers.py)
class SubscriberManager:
    """Manages the list of subscribers for notifications."""

    def __init__(self, storage_file: str = "/tmp/subscribers.json"):
        """Initialize subscriber manager with /tmp storage for Vercel."""
        self.storage_file = Path(storage_file)
        self.storage_file.parent.mkdir(exist_ok=True)
        self._subscribers: Set[int] = self._load_subscribers()

    def _load_subscribers(self) -> Set[int]:
        """Load subscribers from storage file."""
        if not self.storage_file.exists():
            return set()
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('subscribers', []))
        except (json.JSONDecodeError, OSError):
            return set()

    def _save_subscribers(self) -> None:
        """Save subscribers to storage file."""
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {'subscribers': list(self._subscribers)},
                    f,
                    ensure_ascii=False,
                    indent=2
                )
        except OSError:
            pass

    def add_subscriber(self, chat_id: int) -> bool:
        """Add a new subscriber."""
        if chat_id in self._subscribers:
            return False
        self._subscribers.add(chat_id)
        self._save_subscribers()
        return True

    def remove_subscriber(self, chat_id: int) -> bool:
        """Remove a subscriber."""
        if chat_id not in self._subscribers:
            return False
        self._subscribers.remove(chat_id)
        self._save_subscribers()
        return True

    def is_subscribed(self, chat_id: int) -> bool:
        """Check if a chat ID is subscribed."""
        return chat_id in self._subscribers

    def get_subscriber_count(self) -> int:
        """Get the number of subscribers."""
        return len(self._subscribers)


# Cache for film data
_films_cache: Optional[List[Film]] = None
_films_cache_time: Optional[float] = None
CACHE_TTL = 300  # 5 minutes in seconds


# Film scraping functionality
def fetch_current_films() -> List[Film]:
    """
    Fetch current films from Meisengeige website with caching.

    Returns:
        List of Film objects
    """
    global _films_cache, _films_cache_time

    # Check if cache is valid
    current_time = time.time()
    if _films_cache is not None and _films_cache_time is not None:
        cache_age = current_time - _films_cache_time
        if cache_age < CACHE_TTL:
            print(f"[DEBUG] Using cached films data (age: {int(cache_age)}s)")
            return _films_cache

    # Fetch fresh data
    print("[DEBUG] Fetching fresh films data from website...")
    BASE_URL = "https://www.cinecitta.de/programm/meisengeige/"
    TIMEOUT = 30.0

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(BASE_URL)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, 'html.parser')
        film_containers = soup.find_all('li', class_='filmapi-container__list--li')

        films = []
        for container in film_containers:
            film = _parse_single_film(container)
            if film:
                films.append(film)

        # Update cache
        _films_cache = films
        _films_cache_time = current_time
        print(f"[DEBUG] Cached {len(films)} films")

        return films
    except Exception as e:
        print(f"[ERROR] Failed to fetch films: {e}")
        # Return cached data if available, even if expired
        if _films_cache is not None:
            print("[DEBUG] Returning stale cache due to fetch error")
            return _films_cache
        return []


def _parse_single_film(container) -> Optional[Film]:
    """Parse a single film from HTML container."""
    try:
        film_id = container.get('id', '').replace('film-', '') if container.get('id') else None

        title_elem = container.find('h3', class_='text-white')
        title = title_elem.text.strip() if title_elem else None
        if not title:
            return None

        genre_elems = container.find_all('span', class_='px-2 bg-petrol-50')
        genres = [genre.text.strip() for genre in genre_elems]

        fsk_elem = container.find('span', class_=re.compile('age-rating--'))
        fsk_rating = fsk_elem.text.strip() if fsk_elem else None

        duration = None
        duration_elem = container.find('i', class_='icon-clock')
        if duration_elem and duration_elem.parent:
            duration_text = duration_elem.parent.text.strip()
            duration_match = re.search(r'(\d+)\s*min', duration_text)
            if duration_match:
                duration = int(duration_match.group(1))

        desc_elem = container.find('p', class_='leading-tight')
        description = desc_elem.text.strip() if desc_elem else None

        poster_url = None
        img_elem = container.find('img')
        if img_elem and img_elem.get('src'):
            poster_url = img_elem['src']
            if not poster_url.startswith('http'):
                poster_url = f"https://www.cinecitta.de{poster_url}"

        showtimes = _parse_showtimes(container)

        return Film(
            title=title,
            genres=genres,
            fsk_rating=fsk_rating,
            duration=duration,
            description=description,
            poster_url=poster_url,
            film_id=film_id,
            showtimes=showtimes,
        )
    except Exception as e:
        print(f"[ERROR] Error parsing film: {e}")
        return None


def _parse_showtimes(container) -> List[Showtime]:
    """Parse showtimes from film container."""
    showtimes = []
    showtime_section = container.find('div', class_='show_playing_times__content--inner')
    if not showtime_section:
        return showtimes

    table = showtime_section.find('table', class_='film-list-table')
    if not table:
        return showtimes

    dates = []
    thead = table.find('thead')
    if thead:
        header_cells = thead.find_all('th')
        for cell in header_cells[1:]:
            date_text = cell.get_text(strip=True)
            if date_text:
                dates.append(date_text)

    if not dates:
        return showtimes

    tbody = table.find('tbody')
    if not tbody:
        return showtimes

    rows = tbody.find_all('tr')
    for row in rows:
        room_header = row.find('th')
        if not room_header:
            continue

        room_div = room_header.find('div', class_='font-semibold')
        room = room_div.get_text(strip=True) if room_div else "Unknown"

        language = None
        lang_div = room_header.find('div', class_='release-types')
        if lang_div:
            lang_span = lang_div.find('span')
            if lang_span:
                lang_text = lang_span.get_text(strip=True)
                if lang_text:
                    language = lang_text

        time_cells = row.find_all('td')

        for idx, cell in enumerate(time_cells):
            if idx >= len(dates):
                break

            time_link = cell.find('a', class_='performance-link')
            if time_link:
                time_span = time_link.find('span', class_='link-text')
                if time_span:
                    time_text = time_span.get_text(strip=True)
                    if time_text and re.match(r'\d{1,2}:\d{2}', time_text):
                        showtimes.append(
                            Showtime(
                                date=dates[idx],
                                time=time_text,
                                room=room,
                                language=language,
                            )
                        )

    return showtimes


# Initialize subscriber manager
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

subscriber_manager = SubscriberManager()

# Track if bot commands have been set up
_commands_initialized = False


async def setup_bot_commands(bot: Bot):
    """Set up bot command menu (only runs once per container)."""
    global _commands_initialized
    if _commands_initialized:
        return

    try:
        commands = [
            BotCommand("films", "🎥 Показать текущую программу"),
            BotCommand("start", "✨ Подписаться на уведомления"),
            BotCommand("status", "📊 Проверить статус подписки"),
            BotCommand("stop", "❌ Отписаться от уведомлений")
        ]
        await bot.set_my_commands(commands)
        _commands_initialized = True
        print("[INFO] Bot commands menu initialized")
    except Exception as e:
        print(f"[WARNING] Failed to set bot commands: {e}")


async def handle_start_command(bot: Bot, chat_id: int, user_first_name: str) -> str:
    """
    Handle /start command.

    Args:
        chat_id: User's chat ID
        user_first_name: User's first name

    Returns:
        Message to send (or None if photo was sent)
    """
    if subscriber_manager.add_subscriber(chat_id):
        # First time user - send welcome photo with description
        welcome_image_url = "https://www.cinecitta.de/fileadmin/Seitenbanner/Seitenbanner_Meisengeige.jpg.pagespeed.ce.MUHRnnz-ET.jpg"
        caption = (
            f"🎬 <b>Добро пожаловать, {user_first_name}!</b>\n\n"
            "Этот бот следит за программой кинотеатра <b>Meisengeige</b> Nürnberg.\n\n"
            "<b>Возможности:</b>\n"
            "🎥 Просмотр текущей программы\n"
            "✨ Уведомления о новых фильмах\n"
            "🔄 Уведомления об изменениях сеансов\n"
            "❌ Уведомления об удалении фильмов\n\n"
            "Используйте меню команд (☰) для управления подпиской."
        )

        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=welcome_image_url,
                caption=caption,
                parse_mode='HTML'
            )
            return None  # Photo already sent, don't send text message
        except Exception as e:
            print(f"[ERROR] Failed to send welcome photo: {e}")
            # Fallback to text message if photo fails
            return (
                f"🎬 Добро пожаловать, {user_first_name}!\n\n"
                "Вы подписались на обновления программы Meisengeige.\n\n"
                "Возможности:\n"
                "🎥 Просмотр текущей программы\n"
                "✨ Уведомления о новых фильмах\n"
                "🔄 Уведомления об изменениях сеансов\n"
                "❌ Уведомления об удалении фильмов\n\n"
                "Используйте меню команд (☰) для управления подпиской."
            )
    else:
        return (
            f"👋 Привет, {user_first_name}!\n\n"
            "Вы уже подписаны на уведомления.\n\n"
            "Используйте меню команд (☰) для управления подпиской."
        )


async def handle_stop_command(bot: Bot, chat_id: int) -> str:
    """
    Handle /stop command.

    Args:
        chat_id: User's chat ID

    Returns:
        Message to send
    """
    if subscriber_manager.remove_subscriber(chat_id):
        return (
            "👋 Вы отписались от уведомлений Meisengeige.\n\n"
            "Вы можете подписаться снова в любое время используя команду /start."
        )
    else:
        return (
            "Вы не подписаны на уведомления.\n\n"
            "Используйте команду /start для подписки."
        )


async def handle_status_command(bot: Bot, chat_id: int) -> str:
    """
    Handle /status command.

    Args:
        chat_id: User's chat ID

    Returns:
        Message to send (with HTML formatting)
    """
    try:
        print(f"[DEBUG] Checking status for chat_id: {chat_id}")
        is_subscribed = subscriber_manager.is_subscribed(chat_id)
        total_subscribers = subscriber_manager.get_subscriber_count()
        print(f"[DEBUG] is_subscribed={is_subscribed}, total_subscribers={total_subscribers}")

        if is_subscribed:
            return (
                "✅ <b>Подписка активна</b>\n\n"
                f"Вы получаете обновления программы Meisengeige.\n"
                f"Всего подписчиков: {total_subscribers}\n\n"
                "Используйте меню команд (☰) для управления подпиской."
            )
        else:
            return (
                "❌ <b>Не подписаны</b>\n\n"
                "Вы не получаете уведомления.\n\n"
                "Используйте команду /start для подписки."
            )
    except Exception as e:
        print(f"[ERROR] Error in handle_status_command: {e}")
        import traceback
        traceback.print_exc()
        return "Ошибка при проверке статуса. Попробуйте снова."


async def handle_films_command(bot: Bot, chat_id: int) -> None:
    """
    Handle /films command - show brief list of current films with inline buttons.

    Args:
        chat_id: User's chat ID
    """
    try:
        print("[DEBUG] Fetching current films...")
        films = fetch_current_films()

        if not films:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Не удалось загрузить список фильмов. Попробуйте позже."
            )
            return

        # Send header message
        header = f"🎬 <b>Текущая программа Meisengeige</b>\n\nВсего фильмов: {len(films)}\n\n"
        header += "Нажмите на фильм чтобы увидеть детали:"

        # Create inline keyboard with film buttons
        keyboard = []
        for film in films:
            # Create button text with emoji
            button_text = f"🎥 {film.title}"
            # Use film_id or title as callback data
            callback_data = f"film_{film.film_id}" if film.film_id else f"film_{films.index(film)}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=chat_id,
            text=header,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        print(f"[DEBUG] Sent films list with {len(films)} films")

    except Exception as e:
        print(f"[ERROR] Error in handle_films_command: {e}")
        import traceback
        traceback.print_exc()
        await bot.send_message(
            chat_id=chat_id,
            text="Ошибка при загрузке списка фильмов. Попробуйте снова."
        )


async def handle_film_details_callback(bot: Bot, chat_id: int, film_id: str) -> None:
    """
    Handle callback query for film details.

    Args:
        chat_id: User's chat ID
        film_id: Film ID or index from callback data
    """
    try:
        print(f"[DEBUG] Fetching details for film_id: {film_id}")
        films = fetch_current_films()

        # Find the requested film
        film = None
        for f in films:
            if f.film_id == film_id or str(films.index(f)) == film_id:
                film = f
                break

        if not film:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Фильм не найден."
            )
            return

        # Format film details
        caption = f"🎬 <b>{film.title}</b>\n\n"

        if film.genres:
            caption += f"🎭 {', '.join(film.genres)}\n"
        if film.fsk_rating:
            caption += f"👤 {film.fsk_rating}\n"
        if film.duration:
            caption += f"⏱ {film.duration} мин\n"

        caption += "\n"

        if film.description:
            caption += f"{film.description}\n\n"

        if film.showtimes:
            caption += "<b>Сеансы:</b>\n"
            # Group showtimes by date
            for showtime in film.showtimes[:10]:  # Limit to first 10 showtimes
                lang_info = f" ({showtime.language})" if showtime.language else ""
                caption += f"• {showtime.date} {showtime.time} - {showtime.room}{lang_info}\n"

            if len(film.showtimes) > 10:
                caption += f"\n... и еще {len(film.showtimes) - 10} сеансов"

        # Create back button
        keyboard = [[InlineKeyboardButton("◀️ Вернуться к списку", callback_data="back_to_list")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send photo with details
        if film.poster_url:
            await bot.send_photo(
                chat_id=chat_id,
                photo=film.poster_url,
                caption=caption,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode='HTML',
                reply_markup=reply_markup
            )

        print(f"[DEBUG] Sent details for film: {film.title}")

    except Exception as e:
        print(f"[ERROR] Error in handle_film_details_callback: {e}")
        import traceback
        traceback.print_exc()
        await bot.send_message(
            chat_id=chat_id,
            text="Ошибка при загрузке деталей фильма. Попробуйте снова."
        )


async def process_update(update_data: dict) -> dict:
    """
    Process incoming Telegram update.

    Args:
        update_data: JSON data from Telegram

    Returns:
        Response dict
    """
    try:
        # Create bot instance for this request
        bot = Bot(token=BOT_TOKEN)

        # Initialize bot commands menu (runs only once per container)
        await setup_bot_commands(bot)

        update = Update.de_json(update_data, bot)

        # Handle callback queries (inline button clicks)
        if update.callback_query:
            query = update.callback_query
            chat_id = query.message.chat.id
            callback_data = query.data

            print(f"[DEBUG] Processing callback query: '{callback_data}' from chat_id: {chat_id}")

            # Answer callback query to remove loading state
            await bot.answer_callback_query(query.id)

            # Handle callbacks
            if callback_data.startswith('film_'):
                # Show film details
                film_id = callback_data.replace('film_', '')
                await handle_film_details_callback(bot, chat_id, film_id)
            elif callback_data == 'back_to_list':
                # Return to films list
                await handle_films_command(bot, chat_id)

            return {'status': 'success', 'type': 'callback_query'}

        # Handle text messages
        if not update.message or not update.message.text:
            return {'status': 'ignored', 'reason': 'no text message'}

        chat_id = update.message.chat.id
        text = update.message.text.strip()
        user_first_name = update.message.from_user.first_name or "there"

        print(f"[DEBUG] Processing command: '{text}' from chat_id: {chat_id}")

        # Route command (only slash commands)
        response_text = None
        parse_mode = None

        if text == '/start':
            print("[DEBUG] Routing to handle_start_command")
            response_text = await handle_start_command(bot, chat_id, user_first_name)
        elif text == '/stop':
            print("[DEBUG] Routing to handle_stop_command")
            response_text = await handle_stop_command(bot, chat_id)
        elif text == '/status':
            print("[DEBUG] Routing to handle_status_command")
            response_text = await handle_status_command(bot, chat_id)
            parse_mode = 'HTML'
            print(f"[DEBUG] Response text: {response_text[:50]}...")
        elif text == '/films':
            print("[DEBUG] Routing to handle_films_command")
            await handle_films_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        else:
            # Unknown command
            print(f"[DEBUG] Unknown command: {text}")
            response_text = (
                "Неизвестная команда.\n\n"
                "Используйте меню команд (☰) для управления подпиской."
            )

        # Send response (only if response_text is not None)
        # Some handlers (like first-time /start or /films) send their own messages and return None
        if response_text:
            print(f"[DEBUG] Sending response with parse_mode={parse_mode}")
            await bot.send_message(
                chat_id=chat_id,
                text=response_text,
                parse_mode=parse_mode
            )
            print("[DEBUG] Message sent successfully")
        else:
            print("[DEBUG] Response already sent by handler")

        return {'status': 'success', 'command': text}

    except TelegramError as e:
        print(f"Telegram error: {e}")
        return {'status': 'error', 'error': str(e)}
    except Exception as e:
        print(f"Error processing update: {e}")
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'error': str(e)}


# Vercel serverless function handler
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    """Main handler for Vercel serverless function."""

    def do_GET(self):
        """Handle GET requests (health check)."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(
            json.dumps({'status': 'healthy', 'bot': 'meisengeige'}).encode()
        )

    def do_POST(self):
        """Handle POST requests (webhook)."""
        try:
            # Read body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))

            if not data:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(
                    json.dumps({'status': 'error', 'message': 'No data'}).encode()
                )
                return

            # Process update with proper event loop handling
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            result = loop.run_until_complete(process_update(data))

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        except Exception as e:
            print(f"Handler error: {e}")
            import traceback
            traceback.print_exc()

            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(
                json.dumps({'status': 'error', 'message': str(e)}).encode()
            )
