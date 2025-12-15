"""Telegram notification handler."""

import os
from typing import List
from telegram import Bot
from telegram.error import TelegramError

from .models import Film


class TelegramNotifier:
    """Sends notifications to Telegram bot."""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        """
        Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token (from BotFather)
            chat_id: Chat ID to send messages to
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not provided")
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID not provided")

        self.bot = Bot(token=self.bot_token)

    async def send_update_notification(
        self,
        new_films: List[Film],
        removed_films: List[Film],
        updated_films: List[Film],
    ) -> None:
        """
        Send notification about program updates.

        Args:
            new_films: List of newly added films
            removed_films: List of removed films
            updated_films: List of updated films (changed showtimes)
        """
        if not new_films and not removed_films and not updated_films:
            print("No changes detected, skipping notification")
            return

        message = self._format_update_message(new_films, removed_films, updated_films)

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML',
            )
            print("Notification sent successfully")
        except TelegramError as e:
            print(f"Error sending Telegram notification: {e}")
            raise

    def _format_update_message(
        self,
        new_films: List[Film],
        removed_films: List[Film],
        updated_films: List[Film],
    ) -> str:
        """
        Format update message for Telegram.

        Args:
            new_films: List of newly added films
            removed_films: List of removed films
            updated_films: List of updated films

        Returns:
            Formatted message string
        """
        lines = ["🎬 <b>Meisengeige Program Update</b>\n"]

        if new_films:
            lines.append(f"✨ <b>New Films ({len(new_films)}):</b>")
            for film in new_films:
                lines.append(self._format_film(film))
            lines.append("")

        if updated_films:
            lines.append(f"🔄 <b>Updated Films ({len(updated_films)}):</b>")
            for film in updated_films:
                lines.append(self._format_film(film))
            lines.append("")

        if removed_films:
            lines.append(f"❌ <b>Removed Films ({len(removed_films)}):</b>")
            for film in removed_films:
                lines.append(f"• {film.title}")
            lines.append("")

        lines.append("🔗 https://www.cinecitta.de/programm/meisengeige/")

        return "\n".join(lines)

    def _format_film(self, film: Film) -> str:
        """
        Format a single film for display.

        Args:
            film: Film to format

        Returns:
            Formatted film string
        """
        parts = [f"• <b>{film.title}</b>"]

        # Add genres and duration
        if film.genres or film.duration:
            info_parts = []
            if film.genres:
                info_parts.append(", ".join(film.genres))
            if film.duration:
                info_parts.append(f"{film.duration}min")
            parts.append(f"  ({', '.join(info_parts)})")

        # Add showtimes (limit to first 3 for brevity)
        if film.showtimes:
            showtime_count = len(film.showtimes)
            shown_showtimes = film.showtimes[:3]

            for st in shown_showtimes:
                lang_info = f" {st.language}" if st.language else ""
                parts.append(f"  📅 {st.date} {st.time} - {st.room}{lang_info}")

            if showtime_count > 3:
                parts.append(f"  ... and {showtime_count - 3} more showtimes")

        return "\n".join(parts)
