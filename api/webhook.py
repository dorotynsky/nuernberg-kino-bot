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
from pymongo import MongoClient
from telegram import Update, Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError


# Cinema source definitions
CINEMA_SOURCES = {
    'meisengeige': {
        'id': 'meisengeige',
        'display_name': 'Meisengeige',
        'display_name_ru': 'Meisengeige',
        'display_name_de': 'Meisengeige',
        'display_name_en': 'Meisengeige',
        'url': 'https://www.cinecitta.de/programm/meisengeige/',
        'venue': 'Cinecitta Nürnberg',
    },
    'kinderkino': {
        'id': 'kinderkino',
        'display_name': 'Kinderkino (Filmhaus)',
        'display_name_ru': 'Kinderkino (Filmhaus)',
        'display_name_de': 'Kinderkino (Filmhaus)',
        'display_name_en': 'Kinderkino (Filmhaus)',
        'url': 'https://www.kunstkulturquartier.de/filmhaus/programm/kinderkino',
        'venue': 'Filmhaus Nürnberg',
    }
}


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


# MongoDB connection helper
def get_mongodb_database():
    """Get MongoDB database instance."""
    mongodb_uri = os.getenv('MONGODB_URI')
    if not mongodb_uri:
        raise ValueError("MONGODB_URI environment variable not set")

    client = MongoClient(mongodb_uri)
    return client['meisengeige_bot']


# Inline SubscriberManager (MongoDB version with multi-source support)
class SubscriberManager:
    """Manages the list of subscribers for notifications using MongoDB."""

    def __init__(self):
        """Initialize subscriber manager with MongoDB."""
        self.db = get_mongodb_database()
        self.collection = self.db['subscribers']
        # Create index on chat_id for faster queries
        self.collection.create_index('chat_id', unique=True)

    def add_subscription(self, chat_id: int, source_id: str) -> bool:
        """Add subscription to specific source."""
        doc = self.collection.find_one({'chat_id': chat_id})

        if doc:
            # User exists, add source if not already subscribed
            sources = doc.get('sources', [])
            if source_id in sources:
                return False
            sources.append(source_id)
            self.collection.update_one(
                {'chat_id': chat_id},
                {'$set': {'sources': sources}}
            )
            return True
        else:
            # New user
            self.collection.insert_one({
                'chat_id': chat_id,
                'sources': [source_id],
                'language': 'en'
            })
            return True

    def remove_subscription(self, chat_id: int, source_id: str) -> bool:
        """Remove subscription from specific source."""
        doc = self.collection.find_one({'chat_id': chat_id})
        if not doc:
            return False

        sources = doc.get('sources', [])
        if source_id not in sources:
            return False

        sources.remove(source_id)

        if not sources:
            # No sources left, remove user entirely
            self.collection.delete_one({'chat_id': chat_id})
        else:
            self.collection.update_one(
                {'chat_id': chat_id},
                {'$set': {'sources': sources}}
            )
        return True

    def get_subscribers_for_source(self, source_id: str) -> Set[int]:
        """Get all subscribers for a specific source."""
        docs = self.collection.find({'sources': source_id}, {'chat_id': 1})
        return {doc['chat_id'] for doc in docs}

    def get_user_sources(self, chat_id: int) -> List[str]:
        """Get list of sources user is subscribed to."""
        doc = self.collection.find_one({'chat_id': chat_id})
        return doc.get('sources', []) if doc else []

    def is_subscribed(self, chat_id: int, source_id: Optional[str] = None) -> bool:
        """Check if user is subscribed."""
        doc = self.collection.find_one({'chat_id': chat_id})
        if not doc:
            return False
        if source_id is None:
            return len(doc.get('sources', [])) > 0
        return source_id in doc.get('sources', [])

    def get_subscriber_count(self, source_id: Optional[str] = None) -> int:
        """Get subscriber count."""
        if source_id is None:
            return self.collection.count_documents({})
        return self.collection.count_documents({'sources': source_id})

    # Legacy methods for backward compatibility
    def add_subscriber(self, chat_id: int) -> bool:
        """Legacy: Add subscriber to Meisengeige by default."""
        return self.add_subscription(chat_id, 'meisengeige')

    def remove_subscriber(self, chat_id: int) -> bool:
        """Legacy: Remove all subscriptions."""
        result = self.collection.delete_one({'chat_id': chat_id})
        return result.deleted_count > 0

    def get_all_subscribers(self) -> Set[int]:
        """Legacy: Get all subscriber chat IDs."""
        docs = self.collection.find({}, {'chat_id': 1})
        return {doc['chat_id'] for doc in docs}


# Language Manager for user language preferences (MongoDB version)
class LanguageManager:
    """Manages user language preferences using MongoDB."""

    def __init__(self):
        """Initialize language manager with MongoDB."""
        self.db = get_mongodb_database()
        self.collection = self.db['languages']
        # Create index on chat_id for faster queries
        self.collection.create_index('chat_id', unique=True)

    def set_language(self, chat_id: int, language: str) -> None:
        """Set language preference for a user."""
        self.collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'language': language}},
            upsert=True
        )

    def get_language(self, chat_id: int) -> str:
        """Get language preference for a user (default: ru)."""
        doc = self.collection.find_one({'chat_id': chat_id})
        return doc['language'] if doc else 'ru'

    def has_language_set(self, chat_id: int) -> bool:
        """Check if user has explicitly set a language preference."""
        return self.collection.find_one({'chat_id': chat_id}) is not None


# User Version Manager for tracking bot updates
class UserVersionManager:
    """Manages user version tracking for update notifications."""

    def __init__(self):
        """Initialize version manager with MongoDB."""
        self.db = get_mongodb_database()
        self.collection = self.db['user_versions']
        # Create index on chat_id for faster queries
        self.collection.create_index('chat_id', unique=True)

    def set_version(self, chat_id: int, version: str) -> None:
        """Set the bot version that user has seen."""
        self.collection.update_one(
            {'chat_id': chat_id},
            {'$set': {'version': version}},
            upsert=True
        )

    def get_version(self, chat_id: int) -> str:
        """Get the bot version that user has seen (default: '0.0.0')."""
        doc = self.collection.find_one({'chat_id': chat_id})
        return doc['version'] if doc else '0.0.0'


# Bot version and update messages
BOT_VERSION = '1.1.0'

VERSION_UPDATES = {
    '1.1.0': {
        'ru': '''🎉 <b>Обновление бота v1.1.0</b>

<b>Что нового:</b>
• 🌍 Поддержка трёх языков (Русский, Deutsch, English)
• 💾 Постоянное хранение подписок в MongoDB
• 🔄 Подписки больше не теряются при обновлениях
• 🌐 Меню команд на вашем языке Telegram

<b>Новые команды:</b>
• /language - Изменить язык в любое время

Просто продолжайте пользоваться ботом! 🎬''',
        'de': '''🎉 <b>Bot-Update v1.1.0</b>

<b>Was ist neu:</b>
• 🌍 Unterstützung für drei Sprachen (Russisch, Deutsch, Englisch)
• 💾 Dauerhafte Speicherung von Abonnements in MongoDB
• 🔄 Abonnements gehen bei Updates nicht mehr verloren
• 🌐 Befehlsmenü in Ihrer Telegram-Sprache

<b>Neue Befehle:</b>
• /language - Sprache jederzeit ändern

Nutzen Sie den Bot einfach weiter! 🎬''',
        'en': '''🎉 <b>Bot Update v1.1.0</b>

<b>What's new:</b>
• 🌍 Support for three languages (Russian, Deutsch, English)
• 💾 Persistent subscription storage in MongoDB
• 🔄 Subscriptions no longer lost on updates
• 🌐 Command menu in your Telegram language

<b>New commands:</b>
• /language - Change language anytime

Just keep using the bot! 🎬'''
    }
}


# Translations dictionary
TRANSLATIONS = {
    'ru': {
        'choose_language': '🌍 Выберите язык',
        'language_set': '✅ Язык установлен: Русский',
        'welcome_title': '🎬 <b>Добро пожаловать, {name}!</b>',
        'welcome_desc': 'Этот бот следит за программами кинотеатров Нюрнберга:\n• <b>Meisengeige</b> (Cinecitta)\n• <b>Kinderkino</b> (Filmhaus)',
        'capabilities': '<b>Возможности:</b>',
        'capability_view': '🎥 Просмотр текущих программ',
        'capability_new': '✨ Уведомления о новых фильмах',
        'capability_updates': '🔄 Уведомления об изменениях сеансов',
        'capability_removed': '❌ Уведомления об удалении фильмов',
        'use_menu': 'Используйте /sources для выбора источников уведомлений.',
        'already_subscribed': '👋 Привет, {name}!\n\nВы уже подписаны на уведомления.\n\nИспользуйте меню команд (☰) для управления подпиской.',
        'unsubscribed': '👋 Вы отписались от уведомлений Meisengeige.\n\nВы можете подписаться снова в любое время используя команду /start.',
        'not_subscribed': 'Вы не подписаны на уведомления.\n\nИспользуйте команду /start для подписки.',
        'status_active': '✅ <b>Подписка активна</b>\n\nВы получаете обновления программы Meisengeige.\nВсего подписчиков: {count}\n\nИспользуйте меню команд (☰) для управления подпиской.',
        'status_inactive': '❌ <b>Не подписаны</b>\n\nВы не получаете уведомления.\n\nИспользуйте команду /start для подписки.',
        'films_title': '🎬 <b>Текущая программа Meisengeige</b>\n\nВсего фильмов: {count}\n\nНажмите на фильм чтобы увидеть детали:',
        'films_error': '❌ Не удалось загрузить список фильмов. Попробуйте позже.',
        'film_not_found': '❌ Фильм не найден.',
        'showtimes': '<b>Сеансы:</b>',
        'back_to_list': '◀️ Вернуться к списку',
        'unknown_command': 'Неизвестная команда.\n\nИспользуйте меню команд (☰) для управления подпиской.',
        'broadcast_no_permission': '❌ У вас нет прав для отправки рассылок.',
        'broadcast_usage': '📢 Использование: /broadcast <сообщение>\n\nОтправит сообщение всем подписчикам.',
        'broadcast_sending': '📤 Отправка сообщения {count} подписчикам...',
        'broadcast_success': '✅ Сообщение успешно отправлено {success} из {total} подписчиков.',
        'subscribed_to_source': '✅ Вы подписались на {source_name}!\n\nВы будете получать обновления программы этого кинотеатра.',
        'already_subscribed_source': 'ℹ️ Вы уже подписаны на {source_name}',
        'unsubscribed_from_source': '✅ Вы отписались от {source_name}',
        'not_subscribed_source': 'ℹ️ Вы не подписаны на {source_name}',
        'unknown_source': '❌ Неизвестный источник',
        'status_active_multi': '✅ <b>Активные подписки</b>',
        'status_your_subscriptions': '<b>Ваши подписки:</b>',
        'status_subscriber_counts': '<b>Количество подписчиков:</b>',
        'use_sources_cmd': 'Используйте /sources для управления подписками',
        'sources_header': '🎬 <b>Источники программ кинотеатров</b>',
        'sources_your_subscriptions': '<b>Ваши подписки:</b>',
        'sources_available_cinemas': '<b>Доступные кинотеатры:</b>',
    },
    'de': {
        'choose_language': '🌍 Sprache wählen',
        'language_set': '✅ Sprache eingestellt: Deutsch',
        'welcome_title': '🎬 <b>Willkommen, {name}!</b>',
        'welcome_desc': 'Dieser Bot überwacht die Programme der Kinos in Nürnberg:\n• <b>Meisengeige</b> (Cinecitta)\n• <b>Kinderkino</b> (Filmhaus)',
        'capabilities': '<b>Funktionen:</b>',
        'capability_view': '🎥 Aktuelle Programme anzeigen',
        'capability_new': '✨ Benachrichtigungen über neue Filme',
        'capability_updates': '🔄 Benachrichtigungen über Vorstellungsänderungen',
        'capability_removed': '❌ Benachrichtigungen über entfernte Filme',
        'use_menu': 'Verwenden Sie /sources zur Auswahl der Benachrichtigungsquellen.',
        'already_subscribed': '👋 Hallo {name}!\n\nSie sind bereits für Benachrichtigungen angemeldet.\n\nVerwenden Sie das Befehlsmenü (☰) zur Verwaltung.',
        'unsubscribed': '👋 Sie haben sich von Meisengeige-Benachrichtigungen abgemeldet.\n\nSie können sich jederzeit mit /start wieder anmelden.',
        'not_subscribed': 'Sie sind nicht für Benachrichtigungen angemeldet.\n\nVerwenden Sie /start zum Abonnieren.',
        'status_active': '✅ <b>Abonnement aktiv</b>\n\nSie erhalten Meisengeige-Programmupdates.\nGesamtabonnenten: {count}\n\nVerwenden Sie das Befehlsmenü (☰) zur Verwaltung.',
        'status_inactive': '❌ <b>Nicht abonniert</b>\n\nSie erhalten keine Benachrichtigungen.\n\nVerwenden Sie /start zum Abonnieren.',
        'films_title': '🎬 <b>Aktuelles Meisengeige-Programm</b>\n\nFilme insgesamt: {count}\n\nKlicken Sie auf einen Film für Details:',
        'films_error': '❌ Filmliste konnte nicht geladen werden. Bitte später versuchen.',
        'film_not_found': '❌ Film nicht gefunden.',
        'showtimes': '<b>Vorstellungen:</b>',
        'back_to_list': '◀️ Zurück zur Liste',
        'unknown_command': 'Unbekannter Befehl.\n\nVerwenden Sie das Befehlsmenü (☰) zur Verwaltung.',
        'broadcast_no_permission': '❌ Sie haben keine Berechtigung zum Senden von Broadcasts.',
        'broadcast_usage': '📢 Verwendung: /broadcast <Nachricht>\n\nSendet Nachricht an alle Abonnenten.',
        'broadcast_sending': '📤 Sende Nachricht an {count} Abonnenten...',
        'broadcast_success': '✅ Nachricht erfolgreich an {success} von {total} Abonnenten gesendet.',
        'subscribed_to_source': '✅ Sie haben {source_name} abonniert!\n\nSie erhalten Updates zum Programm dieses Kinos.',
        'already_subscribed_source': 'ℹ️ Sie haben {source_name} bereits abonniert',
        'unsubscribed_from_source': '✅ Sie haben {source_name} abbestellt',
        'not_subscribed_source': 'ℹ️ Sie haben {source_name} nicht abonniert',
        'unknown_source': '❌ Unbekannte Quelle',
        'status_active_multi': '✅ <b>Aktive Abonnements</b>',
        'status_your_subscriptions': '<b>Ihre Abonnements:</b>',
        'status_subscriber_counts': '<b>Abonnentenzahlen:</b>',
        'use_sources_cmd': 'Verwenden Sie /sources zur Verwaltung der Abonnements',
        'sources_header': '🎬 <b>Kinoprogramm-Quellen</b>',
        'sources_your_subscriptions': '<b>Ihre Abonnements:</b>',
        'sources_available_cinemas': '<b>Verfügbare Kinos:</b>',
    },
    'en': {
        'choose_language': '🌍 Choose language',
        'language_set': '✅ Language set: English',
        'welcome_title': '🎬 <b>Welcome, {name}!</b>',
        'welcome_desc': 'This bot monitors cinema programs in Nuremberg:\n• <b>Meisengeige</b> (Cinecitta)\n• <b>Kinderkino</b> (Filmhaus)',
        'capabilities': '<b>Features:</b>',
        'capability_view': '🎥 View current programs',
        'capability_new': '✨ Notifications about new films',
        'capability_updates': '🔄 Notifications about showtime changes',
        'capability_removed': '❌ Notifications about removed films',
        'use_menu': 'Use /sources to select notification sources.',
        'already_subscribed': '👋 Hi {name}!\n\nYou are already subscribed to notifications.\n\nUse the command menu (☰) to manage your subscription.',
        'unsubscribed': '👋 You have unsubscribed from Meisengeige notifications.\n\nYou can subscribe again anytime using /start.',
        'not_subscribed': 'You are not subscribed to notifications.\n\nUse /start to subscribe.',
        'status_active': '✅ <b>Subscription Active</b>\n\nYou are receiving Meisengeige program updates.\nTotal subscribers: {count}\n\nUse the command menu (☰) to manage your subscription.',
        'status_inactive': '❌ <b>Not Subscribed</b>\n\nYou are not receiving notifications.\n\nUse /start to subscribe.',
        'films_title': '🎬 <b>Current Meisengeige Program</b>\n\nTotal films: {count}\n\nClick on a film to see details:',
        'films_error': '❌ Failed to load film list. Please try later.',
        'film_not_found': '❌ Film not found.',
        'showtimes': '<b>Showtimes:</b>',
        'back_to_list': '◀️ Back to list',
        'unknown_command': 'Unknown command.\n\nUse the command menu (☰) to manage your subscription.',
        'broadcast_no_permission': '❌ You don\'t have permission to send broadcasts.',
        'broadcast_usage': '📢 Usage: /broadcast <message>\n\nWill send message to all subscribers.',
        'broadcast_sending': '📤 Sending message to {count} subscribers...',
        'broadcast_success': '✅ Message successfully sent to {success} out of {total} subscribers.',
        'subscribed_to_source': '✅ You subscribed to {source_name}!\n\nYou will receive updates for this cinema\'s program.',
        'already_subscribed_source': 'ℹ️ You are already subscribed to {source_name}',
        'unsubscribed_from_source': '✅ You unsubscribed from {source_name}',
        'not_subscribed_source': 'ℹ️ You are not subscribed to {source_name}',
        'unknown_source': '❌ Unknown source',
        'status_active_multi': '✅ <b>Active Subscriptions</b>',
        'status_your_subscriptions': '<b>Your subscriptions:</b>',
        'status_subscriber_counts': '<b>Subscriber counts:</b>',
        'use_sources_cmd': 'Use /sources to manage subscriptions',
        'sources_header': '🎬 <b>Cinema Program Sources</b>',
        'sources_your_subscriptions': '<b>Your subscriptions:</b>',
        'sources_available_cinemas': '<b>Available cinemas:</b>',
    }
}


def get_text(chat_id: int, key: str, **kwargs) -> str:
    """Get translated text for a user."""
    lang = language_manager.get_language(chat_id)
    text = TRANSLATIONS.get(lang, TRANSLATIONS['ru']).get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text


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
language_manager = LanguageManager()
version_manager = UserVersionManager()

# Track when bot commands were last set up (timestamp)
_commands_last_set = 0
_COMMANDS_CACHE_SECONDS = 3600  # Update commands max once per hour


async def setup_bot_commands(bot: Bot):
    """Set up bot command menu (updates max once per hour)."""
    global _commands_last_set

    # Check if commands were set recently (within cache period)
    current_time = time.time()
    if current_time - _commands_last_set < _COMMANDS_CACHE_SECONDS:
        return

    try:
        # Commands in Russian
        commands_ru = [
            BotCommand("films", "🎥 Показать текущую программу"),
            BotCommand("sources", "🎬 Управление источниками"),
            BotCommand("start", "✨ Подписаться на уведомления"),
            BotCommand("status", "📊 Проверить статус подписки"),
            BotCommand("language", "🌍 Выбрать язык"),
            BotCommand("stop", "❌ Отписаться от уведомлений")
        ]

        # Commands in German
        commands_de = [
            BotCommand("films", "🎥 Aktuelles Programm anzeigen"),
            BotCommand("sources", "🎬 Quellen verwalten"),
            BotCommand("start", "✨ Benachrichtigungen abonnieren"),
            BotCommand("status", "📊 Abonnementstatus prüfen"),
            BotCommand("language", "🌍 Sprache wählen"),
            BotCommand("stop", "❌ Benachrichtigungen abbestellen")
        ]

        # Commands in English
        commands_en = [
            BotCommand("films", "🎥 Show current program"),
            BotCommand("sources", "🎬 Manage sources"),
            BotCommand("start", "✨ Subscribe to notifications"),
            BotCommand("status", "📊 Check subscription status"),
            BotCommand("language", "🌍 Change language"),
            BotCommand("stop", "❌ Unsubscribe from notifications")
        ]

        # Set commands for each language
        await bot.set_my_commands(commands_ru, language_code="ru")
        await bot.set_my_commands(commands_de, language_code="de")
        await bot.set_my_commands(commands_en, language_code="en")

        # Set default commands (fallback)
        await bot.set_my_commands(commands_en)

        _commands_last_set = current_time
        print("[INFO] Bot commands menu initialized for all languages")
    except Exception as e:
        print(f"[WARNING] Failed to set bot commands: {e}")


async def handle_start_command(bot: Bot, chat_id: int, user_first_name: str) -> str:
    """
    Handle /start command with language selection.

    Args:
        chat_id: User's chat ID
        user_first_name: User's first name

    Returns:
        Message to send (or None if photo was sent)
    """
    # Check if user has language preference
    current_lang = language_manager.get_language(chat_id)

    # If this is truly first time (no language set and not subscribed), show language selection
    if not language_manager.has_language_set(chat_id) and not subscriber_manager.is_subscribed(chat_id):
        # Show language selection buttons
        keyboard = [
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang_de")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=chat_id,
            text="🌍 Выберите язык / Choose language / Sprache wählen",
            reply_markup=reply_markup
        )
        return None

    # User has language preference or is returning - proceed with subscription
    is_new_subscriber = subscriber_manager.add_subscriber(chat_id)

    if is_new_subscriber:
        # First time subscriber - send welcome photo
        await send_welcome_message(bot, chat_id, user_first_name)
        return None
    else:
        # Already subscribed
        return get_text(chat_id, 'already_subscribed', name=user_first_name)


async def send_welcome_message(bot: Bot, chat_id: int, user_first_name: str):
    """Send welcome message with photo in user's language."""
    welcome_image_url = "https://www.cinecitta.de/fileadmin/Seitenbanner/Seitenbanner_Meisengeige.jpg.pagespeed.ce.MUHRnnz-ET.jpg"

    caption = (
        f"{get_text(chat_id, 'welcome_title', name=user_first_name)}\n\n"
        f"{get_text(chat_id, 'welcome_desc')}\n\n"
        f"{get_text(chat_id, 'capabilities')}\n"
        f"{get_text(chat_id, 'capability_view')}\n"
        f"{get_text(chat_id, 'capability_new')}\n"
        f"{get_text(chat_id, 'capability_updates')}\n"
        f"{get_text(chat_id, 'capability_removed')}\n\n"
        f"{get_text(chat_id, 'use_menu')}"
    )

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=welcome_image_url,
            caption=caption,
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"[ERROR] Failed to send welcome photo: {e}")
        # Fallback to text message if photo fails
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode='HTML'
        )


async def handle_stop_command(bot: Bot, chat_id: int) -> str:
    """
    Handle /stop command.

    Args:
        bot: Bot instance
        chat_id: User's chat ID

    Returns:
        Message to send
    """
    if subscriber_manager.remove_subscriber(chat_id):
        return get_text(chat_id, 'unsubscribed')
    else:
        return get_text(chat_id, 'not_subscribed')


async def handle_status_command(bot: Bot, chat_id: int) -> str:
    """
    Handle /status command - show subscription status for all sources.

    Args:
        bot: Bot instance
        chat_id: User's chat ID

    Returns:
        Message to send (with HTML formatting)
    """
    try:
        print(f"[DEBUG] Checking status for chat_id: {chat_id}")
        user_sources = subscriber_manager.get_user_sources(chat_id)

        if not user_sources:
            return get_text(chat_id, 'status_inactive')

        # Build status message with source details
        lang = language_manager.get_language(chat_id)
        lines = [get_text(chat_id, 'status_active_multi')]

        for source_id in user_sources:
            source = CINEMA_SOURCES.get(source_id)
            if source:
                count = subscriber_manager.get_subscriber_count(source_id)
                name_key = f'display_name_{lang}'
                display_name = source.get(name_key, source['display_name'])
                lines.append(f"• {display_name} ({count} subscribers)")

        lines.append(f"\n{get_text(chat_id, 'use_sources_cmd')}")
        return "\n".join(lines)

    except Exception as e:
        print(f"[ERROR] Error in handle_status_command: {e}")
        import traceback
        traceback.print_exc()
        return get_text(chat_id, 'unknown_command')


async def handle_language_command(bot: Bot, chat_id: int) -> None:
    """
    Handle /language command - show language selection.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
    """
    # Show language selection buttons
    keyboard = [
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="changelang_ru")],
        [InlineKeyboardButton("🇩🇪 Deutsch", callback_data="changelang_de")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="changelang_en")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await bot.send_message(
        chat_id=chat_id,
        text="🌍 Выберите язык / Choose language / Sprache wählen",
        reply_markup=reply_markup
    )


async def handle_sources_command(bot: Bot, chat_id: int) -> None:
    """
    Handle /sources command - show available sources with subscribe/unsubscribe buttons.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
    """
    lang = language_manager.get_language(chat_id)
    user_sources = subscriber_manager.get_user_sources(chat_id)

    # Build message
    message = get_text(chat_id, 'sources_header')

    # Build keyboard with source buttons
    keyboard = []
    for source_id, source_info in CINEMA_SOURCES.items():
        name_key = f'display_name_{lang}'
        display_name = source_info.get(name_key, source_info['display_name'])

        if source_id in user_sources:
            # Subscribed - show unsubscribe button
            button_text = f"✅ {display_name}"
            callback_data = f"unsub:{source_id}"
        else:
            # Not subscribed - show subscribe button
            button_text = f"➕ {display_name}"
            callback_data = f"sub:{source_id}"

        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await bot.send_message(
        chat_id=chat_id,
        text=message,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def check_and_notify_version_update(bot: Bot, chat_id: int) -> None:
    """
    Check if user needs to see version update notification.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
    """
    # Only notify subscribed users
    if not subscriber_manager.is_subscribed(chat_id):
        return

    user_version = version_manager.get_version(chat_id)

    # If user is on old version and there's an update message
    if user_version != BOT_VERSION and BOT_VERSION in VERSION_UPDATES:
        # Get user's language
        lang = language_manager.get_language(chat_id)

        # Get update message in user's language
        update_message = VERSION_UPDATES[BOT_VERSION].get(lang, VERSION_UPDATES[BOT_VERSION]['en'])

        # Send update notification
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=update_message,
                parse_mode='HTML'
            )
            # Update user's version
            version_manager.set_version(chat_id, BOT_VERSION)
        except Exception as e:
            print(f"[WARNING] Failed to send version update to {chat_id}: {e}")


async def handle_broadcast_command(bot: Bot, chat_id: int, message_text: str) -> str:
    """
    Handle /broadcast command - send message to all subscribers (admin only).

    Args:
        bot: Bot instance
        chat_id: User's chat ID
        message_text: Full message text including command

    Returns:
        Response message
    """
    # Check if user is admin
    admin_chat_ids_str = os.getenv('ADMIN_CHAT_IDS', '')
    admin_chat_ids = [int(id.strip()) for id in admin_chat_ids_str.split(',') if id.strip()]

    if chat_id not in admin_chat_ids:
        return get_text(chat_id, 'broadcast_no_permission')

    # Extract message content after /broadcast
    parts = message_text.split(maxsplit=1)
    if len(parts) < 2:
        return get_text(chat_id, 'broadcast_usage')

    broadcast_message = parts[1]

    # Get all subscribers
    all_subscribers = subscriber_manager.get_all_subscribers()
    total = len(all_subscribers)

    if total == 0:
        return "📭 No subscribers to send message to."

    # Send status message
    await bot.send_message(
        chat_id=chat_id,
        text=get_text(chat_id, 'broadcast_sending', count=total)
    )

    # Send message to all subscribers
    success_count = 0
    for subscriber_id in all_subscribers:
        try:
            await bot.send_message(
                chat_id=subscriber_id,
                text=broadcast_message,
                parse_mode='HTML'
            )
            success_count += 1
        except Exception as e:
            print(f"[WARNING] Failed to send broadcast to {subscriber_id}: {e}")

    return get_text(chat_id, 'broadcast_success', success=success_count, total=total)


async def handle_films_command(bot: Bot, chat_id: int) -> None:
    """
    Handle /films command - show brief list of current films with inline buttons.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
    """
    try:
        print("[DEBUG] Fetching current films...")
        films = fetch_current_films()

        if not films:
            await bot.send_message(
                chat_id=chat_id,
                text=get_text(chat_id, 'films_error')
            )
            return

        # Send header message in user's language
        header = get_text(chat_id, 'films_title', count=len(films))

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
            text=get_text(chat_id, 'films_error')
        )


async def handle_film_details_callback(bot: Bot, chat_id: int, film_id: str) -> None:
    """
    Handle callback query for film details.

    Args:
        bot: Bot instance
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
                text=get_text(chat_id, 'film_not_found')
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
            caption += f"{get_text(chat_id, 'showtimes')}\n"
            # Group showtimes by date
            for showtime in film.showtimes[:10]:  # Limit to first 10 showtimes
                lang_info = f" ({showtime.language})" if showtime.language else ""
                caption += f"• {showtime.date} {showtime.time} - {showtime.room}{lang_info}\n"

            if len(film.showtimes) > 10:
                caption += f"\n... и еще {len(film.showtimes) - 10} сеансов"

        # Create back button with translation
        back_button_text = get_text(chat_id, 'back_to_list')
        keyboard = [[InlineKeyboardButton(back_button_text, callback_data="back_to_list")]]
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
            if callback_data.startswith('lang_'):
                # Language selection
                lang = callback_data.replace('lang_', '')
                language_manager.set_language(chat_id, lang)

                # Send confirmation message
                await bot.send_message(
                    chat_id=chat_id,
                    text=get_text(chat_id, 'language_set')
                )

                # Subscribe user and send welcome message
                subscriber_manager.add_subscriber(chat_id)
                user = query.from_user
                user_first_name = user.first_name or "there"
                await send_welcome_message(bot, chat_id, user_first_name)

            elif callback_data.startswith('changelang_'):
                # Language change (from /language command)
                lang = callback_data.replace('changelang_', '')
                language_manager.set_language(chat_id, lang)

                # Send confirmation message in the newly selected language
                await bot.send_message(
                    chat_id=chat_id,
                    text=get_text(chat_id, 'language_set')
                )

            elif callback_data.startswith('film_'):
                # Show film details
                film_id = callback_data.replace('film_', '')
                await handle_film_details_callback(bot, chat_id, film_id)
            elif callback_data == 'back_to_list':
                # Return to films list
                await handle_films_command(bot, chat_id)

            elif callback_data.startswith('sub:'):
                # Subscribe to source
                source_id = callback_data.replace('sub:', '')
                if source_id in CINEMA_SOURCES:
                    source = CINEMA_SOURCES[source_id]
                    if subscriber_manager.add_subscription(chat_id, source_id):
                        message = get_text(chat_id, 'subscribed_to_source', source_name=source['display_name'])
                    else:
                        message = get_text(chat_id, 'already_subscribed_source', source_name=source['display_name'])
                    await bot.send_message(chat_id=chat_id, text=message)
                else:
                    await bot.send_message(chat_id=chat_id, text=get_text(chat_id, 'unknown_source'))

            elif callback_data.startswith('unsub:'):
                # Unsubscribe from source
                source_id = callback_data.replace('unsub:', '')
                if source_id in CINEMA_SOURCES:
                    source = CINEMA_SOURCES[source_id]
                    if subscriber_manager.remove_subscription(chat_id, source_id):
                        message = get_text(chat_id, 'unsubscribed_from_source', source_name=source['display_name'])
                    else:
                        message = get_text(chat_id, 'not_subscribed_source', source_name=source['display_name'])
                    await bot.send_message(chat_id=chat_id, text=message)
                else:
                    await bot.send_message(chat_id=chat_id, text=get_text(chat_id, 'unknown_source'))

            return {'status': 'success', 'type': 'callback_query'}

        # Handle text messages
        if not update.message or not update.message.text:
            return {'status': 'ignored', 'reason': 'no text message'}

        chat_id = update.message.chat.id
        text = update.message.text.strip()
        user_first_name = update.message.from_user.first_name or "there"

        print(f"[DEBUG] Processing command: '{text}' from chat_id: {chat_id}")

        # Check and notify about version updates (for subscribed users)
        await check_and_notify_version_update(bot, chat_id)

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
        elif text == '/language':
            print("[DEBUG] Routing to handle_language_command")
            await handle_language_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        elif text == '/films':
            print("[DEBUG] Routing to handle_films_command")
            await handle_films_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        elif text == '/sources':
            print("[DEBUG] Routing to handle_sources_command")
            await handle_sources_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        elif text.startswith('/broadcast'):
            print("[DEBUG] Routing to handle_broadcast_command")
            response_text = await handle_broadcast_command(bot, chat_id, text)
        else:
            # Unknown command
            print(f"[DEBUG] Unknown command: {text}")
            response_text = get_text(chat_id, 'unknown_command')

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
