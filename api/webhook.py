"""Vercel serverless function for Telegram webhook."""

import json
import logging
import os
import sys
import time
from typing import List, Optional, Set

# Add project root to path so we can import from src/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

from pymongo import MongoClient
from telegram import Update, Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from src.models import Film
from src.scraper import MeisengeigeScraper
from src.filmhaus_scraper import FilmhausScraper


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


# MongoDB connection helper — lazy singleton
_mongo_db = None


def get_mongodb_database():
    """Get MongoDB database instance (shared singleton, lazy init)."""
    global _mongo_db
    if _mongo_db is None:
        mongodb_uri = os.getenv('MONGODB_URI')
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        try:
            client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            _mongo_db = client['nuernberg_kino_bot']
        except Exception:
            raise ConnectionError("Failed to connect to MongoDB")
    return _mongo_db


class BaseMongoManager:
    """Base class for MongoDB collection managers with lazy init."""

    collection_name: str = None

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_mongodb_database()[self.collection_name]
        return self._collection


class SubscriberManager(BaseMongoManager):
    """Manages the list of subscribers for notifications using MongoDB."""

    collection_name = 'subscribers'

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


class LanguageManager(BaseMongoManager):
    """Manages user language preferences using MongoDB."""

    collection_name = 'languages'

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


class UserVersionManager(BaseMongoManager):
    """Manages user version tracking for update notifications."""

    collection_name = 'user_versions'

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
BOT_VERSION = '1.2.0'

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
        'capability_view': '🎥 Просмотр текущих программ кинотеатров',
        'capability_new': '✨ Уведомления о новых фильмах',
        'capability_updates': '🔄 Уведомления об изменениях сеансов',
        'capability_removed': '❌ Уведомления об удалении фильмов',
        'use_menu': 'Используйте меню для просмотра программ или подписки на уведомления.',
        'already_subscribed': '👋 Привет, {name}!\n\nВы уже подписаны на уведомления.\n\nИспользуйте меню команд (☰) для управления подпиской.',
        'unsubscribed': '👋 Вы отписались от всех уведомлений кинотеатров.\n\nВсе подписки были удалены. Вы можете подписаться снова в любое время используя /sources.',
        'not_subscribed': 'Вы не подписаны на уведомления.\n\nИспользуйте команду /start для подписки.',
        'status_active': '✅ <b>Подписка активна</b>\n\nВы получаете обновления программы Meisengeige.\nВсего подписчиков: {count}\n\nИспользуйте меню команд (☰) для управления подпиской.',
        'status_inactive': '❌ <b>Не подписаны</b>\n\nВы не получаете уведомления.\n\nИспользуйте команду /start для подписки.',
        'films_select_source': '🎬 <b>Выберите кинотеатр</b>\n\nВыберите источник для просмотра программы:',
        'films_title': '🎬 <b>Текущая программа Meisengeige</b>\n\nВсего фильмов: {count}\n\nНажмите на фильм чтобы увидеть детали:',
        'films_title_source': '🎬 <b>Текущая программа {source_name}</b>\n\nВсего фильмов: {count}\n\nНажмите на фильм чтобы увидеть детали:',
        'films_error': '❌ Не удалось загрузить список фильмов. Попробуйте позже.',
        'film_not_found': '❌ Фильм не найден.',
        'showtimes': '<b>Сеансы:</b>',
        'back_to_list': '◀️ Вернуться к списку',
        'back_to_sources': '◀️ Вернуться к выбору кинотеатра',
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
        'duration_min': 'мин',
        'more_showtimes': '... и ещё {count} сеансов',
        'film_details_error': '❌ Ошибка при загрузке деталей фильма. Попробуйте снова.',
    },
    'de': {
        'choose_language': '🌍 Sprache wählen',
        'language_set': '✅ Sprache eingestellt: Deutsch',
        'welcome_title': '🎬 <b>Willkommen, {name}!</b>',
        'welcome_desc': 'Dieser Bot überwacht die Programme der Kinos in Nürnberg:\n• <b>Meisengeige</b> (Cinecitta)\n• <b>Kinderkino</b> (Filmhaus)',
        'capabilities': '<b>Funktionen:</b>',
        'capability_view': '🎥 Aktuelle Kinoprogramme anzeigen',
        'capability_new': '✨ Benachrichtigungen über neue Filme',
        'capability_updates': '🔄 Benachrichtigungen über Vorstellungsänderungen',
        'capability_removed': '❌ Benachrichtigungen über entfernte Filme',
        'use_menu': 'Verwenden Sie das Menü zur Ansicht der Programme oder zum Abonnieren von Benachrichtigungen.',
        'already_subscribed': '👋 Hallo {name}!\n\nSie sind bereits für Benachrichtigungen angemeldet.\n\nVerwenden Sie das Befehlsmenü (☰) zur Verwaltung.',
        'unsubscribed': '👋 Sie haben sich von allen Kino-Benachrichtigungen abgemeldet.\n\nAlle Abonnements wurden entfernt. Sie können sich jederzeit mit /sources wieder anmelden.',
        'not_subscribed': 'Sie sind nicht für Benachrichtigungen angemeldet.\n\nVerwenden Sie /start zum Abonnieren.',
        'status_active': '✅ <b>Abonnement aktiv</b>\n\nSie erhalten Meisengeige-Programmupdates.\nGesamtabonnenten: {count}\n\nVerwenden Sie das Befehlsmenü (☰) zur Verwaltung.',
        'status_inactive': '❌ <b>Nicht abonniert</b>\n\nSie erhalten keine Benachrichtigungen.\n\nVerwenden Sie /start zum Abonnieren.',
        'films_select_source': '🎬 <b>Kino wählen</b>\n\nWählen Sie die Quelle zur Ansicht des Programms:',
        'films_title': '🎬 <b>Aktuelles Meisengeige-Programm</b>\n\nFilme insgesamt: {count}\n\nKlicken Sie auf einen Film für Details:',
        'films_title_source': '🎬 <b>Aktuelles {source_name}-Programm</b>\n\nFilme insgesamt: {count}\n\nKlicken Sie auf einen Film für Details:',
        'films_error': '❌ Filmliste konnte nicht geladen werden. Bitte später versuchen.',
        'film_not_found': '❌ Film nicht gefunden.',
        'showtimes': '<b>Vorstellungen:</b>',
        'back_to_list': '◀️ Zurück zur Liste',
        'back_to_sources': '◀️ Zurück zur Kinoauswahl',
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
        'duration_min': 'Min',
        'more_showtimes': '... und {count} weitere Vorstellungen',
        'film_details_error': '❌ Filmdetails konnten nicht geladen werden. Bitte versuchen Sie es erneut.',
    },
    'en': {
        'choose_language': '🌍 Choose language',
        'language_set': '✅ Language set: English',
        'welcome_title': '🎬 <b>Welcome, {name}!</b>',
        'welcome_desc': 'This bot monitors cinema programs in Nuremberg:\n• <b>Meisengeige</b> (Cinecitta)\n• <b>Kinderkino</b> (Filmhaus)',
        'capabilities': '<b>Features:</b>',
        'capability_view': '🎥 View current cinema programs',
        'capability_new': '✨ Notifications about new films',
        'capability_updates': '🔄 Notifications about showtime changes',
        'capability_removed': '❌ Notifications about removed films',
        'use_menu': 'Use the menu to view programs or subscribe to notifications.',
        'already_subscribed': '👋 Hi {name}!\n\nYou are already subscribed to notifications.\n\nUse the command menu (☰) to manage your subscription.',
        'unsubscribed': '👋 You have unsubscribed from all cinema notifications.\n\nAll subscriptions have been removed. You can subscribe again anytime using /sources.',
        'not_subscribed': 'You are not subscribed to notifications.\n\nUse /start to subscribe.',
        'status_active': '✅ <b>Subscription Active</b>\n\nYou are receiving Meisengeige program updates.\nTotal subscribers: {count}\n\nUse the command menu (☰) to manage your subscription.',
        'status_inactive': '❌ <b>Not Subscribed</b>\n\nYou are not receiving notifications.\n\nUse /start to subscribe.',
        'films_select_source': '🎬 <b>Select Cinema</b>\n\nChoose a source to view the program:',
        'films_title': '🎬 <b>Current Meisengeige Program</b>\n\nTotal films: {count}\n\nClick on a film to see details:',
        'films_title_source': '🎬 <b>Current {source_name} Program</b>\n\nTotal films: {count}\n\nClick on a film to see details:',
        'films_error': '❌ Failed to load film list. Please try later.',
        'film_not_found': '❌ Film not found.',
        'showtimes': '<b>Showtimes:</b>',
        'back_to_list': '◀️ Back to list',
        'back_to_sources': '◀️ Back to cinema selection',
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
        'duration_min': 'min',
        'more_showtimes': '... and {count} more showtimes',
        'film_details_error': '❌ Failed to load film details. Please try again.',
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
MAX_DESCRIPTION_LENGTH = 600  # Telegram photo caption limit is 1024 chars, leave room for metadata


# Film scraping functionality
def fetch_current_films(source_id: str = 'meisengeige') -> List[Film]:
    """
    Fetch current films from cinema website with caching.

    Args:
        source_id: Cinema source ID ('meisengeige' or 'kinderkino')

    Returns:
        List of Film objects
    """
    global _films_cache, _films_cache_time

    # Per-source cache key
    cache_key = f"{source_id}_cache"
    cache_time_key = f"{source_id}_cache_time"

    # Check if cache is valid
    current_time = time.time()
    if cache_key in globals() and cache_time_key in globals():
        cache_age = current_time - globals()[cache_time_key]
        if cache_age < CACHE_TTL:
            logger.debug(f"Using cached films data for {source_id} (age: {int(cache_age)}s)")
            return globals()[cache_key]

    # Fetch fresh data based on source
    logger.debug(f"Fetching fresh films data from {source_id}...")

    if source_id == 'meisengeige':
        films = fetch_meisengeige_films()
    elif source_id == 'kinderkino':
        films = fetch_kinderkino_films()
    else:
        logger.error(f"Unknown source_id: {source_id}")
        return []

    # Update cache
    globals()[cache_key] = films
    globals()[cache_time_key] = current_time

    return films


def fetch_meisengeige_films() -> List[Film]:
    """Fetch films from Meisengeige website using src/ scraper."""
    try:
        with MeisengeigeScraper() as scraper:
            films = scraper.scrape()
        logger.debug(f"Fetched {len(films)} films from Meisengeige")
        return films
    except Exception as e:
        logger.error(f"Failed to fetch Meisengeige films: {e}")
        return []


def fetch_kinderkino_films() -> List[Film]:
    """Fetch films from Kinderkino (Filmhaus) website using src/ scraper."""
    try:
        with FilmhausScraper() as scraper:
            films = scraper.scrape()
        logger.debug(f"Fetched {len(films)} films from Kinderkino")
        return films
    except Exception as e:
        logger.error(f"Failed to fetch Kinderkino films: {e}")
        return []


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


def get_commands_for_language(lang: str) -> list:
    """Get bot commands for a specific language."""
    commands_by_lang = {
        'ru': [
            BotCommand("films", "🎥 Показать текущую программу"),
            BotCommand("sources", "🎬 Управление подписками"),
            BotCommand("status", "📊 Проверить статус подписки"),
            BotCommand("language", "🌍 Выбрать язык"),
            BotCommand("stop", "❌ Отписаться от всех уведомлений")
        ],
        'de': [
            BotCommand("films", "🎥 Aktuelles Programm anzeigen"),
            BotCommand("sources", "🎬 Abonnements verwalten"),
            BotCommand("status", "📊 Abonnementstatus prüfen"),
            BotCommand("language", "🌍 Sprache wählen"),
            BotCommand("stop", "❌ Alle Benachrichtigungen abbestellen")
        ],
        'en': [
            BotCommand("films", "🎥 Show current program"),
            BotCommand("sources", "🎬 Manage subscriptions"),
            BotCommand("status", "📊 Check subscription status"),
            BotCommand("language", "🌍 Change language"),
            BotCommand("stop", "❌ Unsubscribe from all notifications")
        ]
    }
    return commands_by_lang.get(lang, commands_by_lang['en'])


async def set_user_commands(bot: Bot, chat_id: int, lang: str):
    """Set bot commands menu for a specific user in their chosen language."""
    try:
        from telegram import BotCommandScopeChat

        commands = get_commands_for_language(lang)
        scope = BotCommandScopeChat(chat_id=chat_id)

        await bot.set_my_commands(commands, scope=scope)
        logger.info(f"Set commands for user {chat_id} in language {lang}")
    except Exception as e:
        logger.warning(f"Failed to set user-specific commands: {e}")


async def setup_bot_commands(bot: Bot):
    """Set up bot command menu (updates max once per hour)."""
    global _commands_last_set

    # Check if commands were set recently (within cache period)
    current_time = time.time()
    if current_time - _commands_last_set < _COMMANDS_CACHE_SECONDS:
        return

    try:
        # Set commands for each language globally
        await bot.set_my_commands(get_commands_for_language('ru'), language_code="ru")
        await bot.set_my_commands(get_commands_for_language('de'), language_code="de")
        await bot.set_my_commands(get_commands_for_language('en'), language_code="en")

        # Set default commands (fallback)
        await bot.set_my_commands(get_commands_for_language('en'))

        _commands_last_set = current_time
        logger.info("Bot commands menu initialized for all languages")
    except Exception as e:
        logger.warning(f"Failed to set bot commands: {e}")


async def handle_start_command(bot: Bot, chat_id: int, user_first_name: str) -> Optional[str]:
    """
    Handle /start command with language selection.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
        user_first_name: User's first name

    Returns:
        Message to send (or None if photo was sent)
    """
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

    # User has language preference - send welcome message without auto-subscription
    # Check if user is already subscribed to any source
    if subscriber_manager.is_subscribed(chat_id):
        # Already subscribed
        return get_text(chat_id, 'already_subscribed', name=user_first_name)
    else:
        # New user - send welcome message without auto-subscribing
        await send_welcome_message(bot, chat_id, user_first_name)
        return None


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
        logger.error(f"Failed to send welcome photo: {e}")
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
        logger.debug(f"Checking status for chat_id: {chat_id}")
        user_sources = subscriber_manager.get_user_sources(chat_id)

        if not user_sources:
            return get_text(chat_id, 'status_inactive')

        # Build status message with source details
        lang = language_manager.get_language(chat_id)
        lines = [get_text(chat_id, 'status_active_multi')]

        for source_id in user_sources:
            source = CINEMA_SOURCES.get(source_id)
            if source:
                name_key = f'display_name_{lang}'
                display_name = source.get(name_key, source['display_name'])
                lines.append(f"• {display_name}")

        lines.append(f"\n{get_text(chat_id, 'use_sources_cmd')}")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Error in handle_status_command: {e}", exc_info=True)
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
            logger.warning(f"Failed to send version update to {chat_id}: {e}")


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
    admin_chat_ids = [int(cid.strip()) for cid in admin_chat_ids_str.split(',') if cid.strip()]

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
            logger.warning(f"Failed to send broadcast to {subscriber_id}: {e}")

    return get_text(chat_id, 'broadcast_success', success=success_count, total=total)


async def handle_films_command(bot: Bot, chat_id: int) -> None:
    """
    Handle /films command - show cinema source selection.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
    """
    try:
        # Show source selection buttons
        keyboard = []
        for source_id, source in CINEMA_SOURCES.items():
            button_text = f"🎬 {source['display_name']}"
            callback_data = f"films_source:{source_id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=chat_id,
            text=get_text(chat_id, 'films_select_source'),
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        logger.debug("Sent cinema source selection for films")

    except Exception as e:
        logger.error(f"Error in handle_films_command: {e}", exc_info=True)
        await bot.send_message(
            chat_id=chat_id,
            text=get_text(chat_id, 'films_error')
        )


async def handle_films_list(bot: Bot, chat_id: int, source_id: str) -> None:
    """
    Handle showing film list for a specific source.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
        source_id: Cinema source ID
    """
    try:
        logger.debug(f"Fetching films for source: {source_id}")
        films = fetch_current_films(source_id)

        if not films:
            await bot.send_message(
                chat_id=chat_id,
                text=get_text(chat_id, 'films_error')
            )
            return

        # Get source display name
        source_name = CINEMA_SOURCES[source_id]['display_name']

        # Send header message in user's language
        header = get_text(chat_id, 'films_title_source', source_name=source_name, count=len(films))

        # Create inline keyboard with film buttons
        keyboard = []
        for i, film in enumerate(films):
            # Create button text with emoji and age rating
            age_rating = ""
            if film.fsk_rating:
                # Extract age number from FSK rating (e.g., "FSK: 6" -> "6+")
                fsk_text = film.fsk_rating.replace("FSK:", "").replace("FSK", "").strip()
                if fsk_text and fsk_text[0].isdigit():
                    age_rating = f" ({fsk_text}+)"

            button_text = f"🎥 {film.title}{age_rating}"
            # Use source-specific callback data
            callback_data = f"film_{source_id}_{film.film_id}" if film.film_id else f"film_{source_id}_{i}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        # Add back button
        keyboard.append([InlineKeyboardButton(get_text(chat_id, 'back_to_sources'), callback_data='back_to_film_sources')])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=chat_id,
            text=header,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        logger.debug(f"Sent films list with {len(films)} films from {source_name}")

    except Exception as e:
        logger.error(f"Error in handle_films_list: {e}", exc_info=True)
        await bot.send_message(
            chat_id=chat_id,
            text=get_text(chat_id, 'films_error')
        )


async def handle_film_details_callback(bot: Bot, chat_id: int, film_data: str) -> None:
    """
    Handle callback query for film details.

    Args:
        bot: Bot instance
        chat_id: User's chat ID
        film_data: Film data in format "source_id_film_id" or just "film_id" (legacy)
    """
    try:
        logger.debug(f"Fetching details for film_data: {film_data}")

        # Parse source_id and film_id from callback data
        # New format: "meisengeige_123" or "kinderkino_5"
        # Legacy format: "123" (assume meisengeige)
        parts = film_data.split('_', 1)
        if len(parts) == 2 and parts[0] in CINEMA_SOURCES:
            source_id = parts[0]
            film_id = parts[1]
        else:
            # Legacy format or single-part ID - assume meisengeige
            source_id = 'meisengeige'
            film_id = film_data

        films = fetch_current_films(source_id)

        # Find the requested film
        film = None
        for i, f in enumerate(films):
            if f.film_id == film_id or str(i) == film_id:
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
            caption += f"⏱ {film.duration} {get_text(chat_id, 'duration_min')}\n"

        caption += "\n"

        if film.description:
            desc = film.description
            # Telegram photo caption limit is 1024 chars — leave room for showtimes
            max_desc = MAX_DESCRIPTION_LENGTH
            if len(desc) > max_desc:
                desc = desc[:max_desc - 3] + "..."
            caption += f"{desc}\n\n"

        if film.showtimes:
            caption += f"{get_text(chat_id, 'showtimes')}\n"
            # Group showtimes by date
            for showtime in film.showtimes[:10]:  # Limit to first 10 showtimes
                lang_info = f" ({showtime.language})" if showtime.language else ""
                caption += f"• {showtime.date} {showtime.time} - {showtime.room}{lang_info}\n"

            if len(film.showtimes) > 10:
                caption += f"\n{get_text(chat_id, 'more_showtimes', count=len(film.showtimes) - 10)}"

        # Create back button with translation
        back_button_text = get_text(chat_id, 'back_to_list')
        keyboard = [[InlineKeyboardButton(back_button_text, callback_data=f"back_to_list:{source_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send photo with details
        if film.poster_url:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=film.poster_url,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            except TelegramError:
                # Fallback if photo/caption fails (e.g. caption too long, invalid URL)
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
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

        logger.debug(f"Sent details for film: {film.title}")

    except Exception as e:
        logger.error(f"Error in handle_film_details_callback: {e}", exc_info=True)
        await bot.send_message(
            chat_id=chat_id,
            text=get_text(chat_id, 'film_details_error')
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

            logger.debug(f"Processing callback query: '{callback_data}' from chat_id: {chat_id}")

            # Answer callback query to remove loading state
            await bot.answer_callback_query(query.id)

            # Handle callbacks
            if callback_data.startswith('lang_'):
                # Language selection
                lang = callback_data.replace('lang_', '')
                language_manager.set_language(chat_id, lang)

                # Set user-specific command menu in their language
                await set_user_commands(bot, chat_id, lang)

                # Send confirmation message
                await bot.send_message(
                    chat_id=chat_id,
                    text=get_text(chat_id, 'language_set')
                )

                # Send welcome message without auto-subscribing
                user = query.from_user
                user_first_name = user.first_name or "there"
                await send_welcome_message(bot, chat_id, user_first_name)

            elif callback_data.startswith('changelang_'):
                # Language change (from /language command)
                lang = callback_data.replace('changelang_', '')
                language_manager.set_language(chat_id, lang)

                # Set user-specific command menu in their language
                await set_user_commands(bot, chat_id, lang)

                # Send confirmation message in the newly selected language
                await bot.send_message(
                    chat_id=chat_id,
                    text=get_text(chat_id, 'language_set')
                )

            elif callback_data.startswith('film_'):
                # Show film details
                film_data = callback_data.replace('film_', '')
                await handle_film_details_callback(bot, chat_id, film_data)

            elif callback_data.startswith('films_source:'):
                # Show film list for selected source
                source_id = callback_data.replace('films_source:', '')
                if source_id in CINEMA_SOURCES:
                    await handle_films_list(bot, chat_id, source_id)
                else:
                    await bot.send_message(chat_id=chat_id, text=get_text(chat_id, 'unknown_source'))

            elif callback_data == 'back_to_film_sources':
                # Return to source selection
                await handle_films_command(bot, chat_id)

            elif callback_data.startswith('back_to_list:'):
                # Return to films list for specific source
                source_id = callback_data.replace('back_to_list:', '')
                if source_id in CINEMA_SOURCES:
                    await handle_films_list(bot, chat_id, source_id)
                else:
                    await bot.send_message(chat_id=chat_id, text=get_text(chat_id, 'unknown_source'))

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

        logger.debug(f"Processing command: '{text}' from chat_id: {chat_id}")

        # Check and notify about version updates (for subscribed users)
        # await check_and_notify_version_update(bot, chat_id)

        # Route command (only slash commands)
        response_text = None
        parse_mode = None

        if text == '/start':
            logger.debug("Routing to handle_start_command")
            response_text = await handle_start_command(bot, chat_id, user_first_name)
        elif text == '/stop':
            logger.debug("Routing to handle_stop_command")
            response_text = await handle_stop_command(bot, chat_id)
        elif text == '/status':
            logger.debug("Routing to handle_status_command")
            response_text = await handle_status_command(bot, chat_id)
            parse_mode = 'HTML'
            logger.debug(f"Response text: {response_text[:50]}...")
        elif text == '/language':
            logger.debug("Routing to handle_language_command")
            await handle_language_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        elif text == '/films':
            logger.debug("Routing to handle_films_command")
            await handle_films_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        elif text == '/sources':
            logger.debug("Routing to handle_sources_command")
            await handle_sources_command(bot, chat_id)
            return {'status': 'success', 'command': text}
        elif text.startswith('/broadcast'):
            logger.debug("Routing to handle_broadcast_command")
            response_text = await handle_broadcast_command(bot, chat_id, text)
        else:
            # Unknown command
            logger.debug(f"Unknown command: {text}")
            response_text = get_text(chat_id, 'unknown_command')

        # Send response (only if response_text is not None)
        # Some handlers (like first-time /start or /films) send their own messages and return None
        if response_text:
            logger.debug(f"Sending response with parse_mode={parse_mode}")
            await bot.send_message(
                chat_id=chat_id,
                text=response_text,
                parse_mode=parse_mode
            )
            logger.debug("Message sent successfully")
        else:
            logger.debug("Response already sent by handler")

        return {'status': 'success', 'command': text}

    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        return {'status': 'error', 'error': str(e)}
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
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
            json.dumps({'status': 'healthy', 'bot': 'nuernberg-kino-bot'}).encode()
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
            logger.error(f"Handler error: {e}", exc_info=True)

            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(
                json.dumps({'status': 'error', 'message': str(e)}).encode()
            )
