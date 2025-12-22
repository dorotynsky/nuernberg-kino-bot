"""Telegram notification handler."""

import os
from typing import List, Set
from telegram import Bot
from telegram.error import TelegramError

from .models import Film
from .subscribers import SubscriberManager


class TelegramNotifier:
    """Sends notifications to Telegram bot."""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        """
        Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token (from BotFather)
            chat_id: Optional single chat ID (for backward compatibility)
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")

        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not provided")

        self.bot = Bot(token=self.bot_token)
        self.subscriber_manager = SubscriberManager()

        # For backward compatibility: if chat_id is provided, add it as subscriber
        if chat_id:
            try:
                self.subscriber_manager.add_subscriber(int(chat_id))
            except ValueError:
                pass

        # Also check environment variable
        env_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if env_chat_id:
            try:
                self.subscriber_manager.add_subscriber(int(env_chat_id))
            except ValueError:
                pass

    async def send_update_notification(
        self,
        source_id: str,
        source_display_name: str,
        source_url: str,
        new_films: List[Film],
        removed_films: List[Film],
        updated_films: List[Film],
    ) -> None:
        """
        Send notification about program updates with film posters.

        Args:
            source_id: Source identifier
            source_display_name: Human-readable source name
            source_url: Source program URL
            new_films: List of newly added films
            removed_films: List of removed films
            updated_films: List of updated films (changed showtimes)
        """
        if not new_films and not removed_films and not updated_films:
            print("No changes detected, skipping notification")
            return

        # Get subscribers for this specific source
        subscribers = self.subscriber_manager.get_subscribers_for_source(source_id)

        if not subscribers:
            print(f"No subscribers for {source_display_name}, skipping notification")
            return

        print(f"Sending {source_display_name} notifications to {len(subscribers)} subscriber(s)...")

        success_count = 0
        error_count = 0

        for chat_id in subscribers:
            try:
                # Send header message
                header = self._format_header(
                    source_display_name, source_url, new_films, removed_films, updated_films
                )
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=header,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                )

                # Send new films with photos
                if new_films:
                    for film in new_films[:10]:  # Limit to 10
                        await self._send_film_with_photo(film, "✨ New Film", chat_id)

                # Send updated films with photos
                if updated_films:
                    for film in updated_films[:10]:  # Limit to 10
                        await self._send_film_with_photo(film, "🔄 Updated", chat_id)

                # Send removed films summary
                if removed_films:
                    removed_text = "❌ <b>Removed Films:</b>\n"
                    for film in removed_films:
                        removed_text += f"• {film.title}\n"
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=removed_text,
                        parse_mode='HTML',
                    )

                success_count += 1
            except TelegramError as e:
                error_count += 1
                print(f"Error sending notification to {chat_id}: {e}")
                # Continue with other subscribers

        print(f"✅ Sent to {success_count} subscriber(s), ❌ {error_count} failed")

    async def _send_film_with_photo(self, film: Film, prefix: str, chat_id: int) -> None:
        """
        Send a single film with poster image and details.

        Args:
            film: Film to send
            prefix: Label prefix (e.g., "✨ New Film", "🔄 Updated")
            chat_id: Telegram chat ID to send to
        """
        caption = self._format_film_caption(film, prefix)

        if film.poster_url:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=film.poster_url,
                    caption=caption,
                    parse_mode='HTML',
                )
            except TelegramError as e:
                # If photo fails, send as text message
                print(f"Failed to send photo for {film.title}: {e}")
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode='HTML',
                )
        else:
            # No poster - send as text
            await self.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode='HTML',
            )

    def _format_header(
        self,
        source_display_name: str,
        source_url: str,
        new_films: List[Film],
        removed_films: List[Film],
        updated_films: List[Film],
    ) -> str:
        """
        Format header message with summary.

        Args:
            source_display_name: Human-readable source name
            source_url: Source program URL
            new_films: List of newly added films
            removed_films: List of removed films
            updated_films: List of updated films

        Returns:
            Formatted header string
        """
        lines = [f"🎬 <b>{source_display_name} Program Update</b>\n"]

        summary_parts = []
        if new_films:
            summary_parts.append(f"✨ {len(new_films)} new film(s)")
        if updated_films:
            summary_parts.append(f"🔄 {len(updated_films)} updated")
        if removed_films:
            summary_parts.append(f"❌ {len(removed_films)} removed")

        if summary_parts:
            lines.append(", ".join(summary_parts))

        lines.append(f"\n🔗 {source_url}")

        return "\n".join(lines)

    def _format_film_caption(self, film: Film, prefix: str) -> str:
        """
        Format film information as photo caption.

        Args:
            film: Film to format
            prefix: Label prefix

        Returns:
            Formatted caption string
        """
        lines = [f"{prefix}: <b>{film.title}</b>\n"]

        # Add genres, FSK, and duration
        info_parts = []
        if film.genres:
            info_parts.append(", ".join(film.genres))
        if film.fsk_rating:
            info_parts.append(film.fsk_rating)
        if film.duration:
            info_parts.append(f"{film.duration}min")

        if info_parts:
            lines.append(" | ".join(info_parts))
            lines.append("")

        # Add description (truncate if too long)
        if film.description:
            desc = film.description
            if len(desc) > 200:
                desc = desc[:197] + "..."
            lines.append(desc)
            lines.append("")

        # Add showtimes
        if film.showtimes:
            lines.append("<b>Showtimes:</b>")
            showtime_count = len(film.showtimes)
            shown_showtimes = film.showtimes[:5]  # Show up to 5

            for st in shown_showtimes:
                lang_info = f" ({st.language})" if st.language else ""
                lines.append(f"📅 {st.date} {st.time} - {st.room}{lang_info}")

            if showtime_count > 5:
                lines.append(f"... +{showtime_count - 5} more")

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
