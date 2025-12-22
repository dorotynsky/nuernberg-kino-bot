"""Telegram bot command handlers."""

import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from .subscribers import SubscriberManager
from .source_registry import SourceRegistry
from .scraper import MeisengeigeScraper
from .filmhaus_scraper import FilmhausScraper


class MeisengeigeBotCommands:
    """Handles Telegram bot commands for subscription management."""

    def __init__(self, bot_token: str = None):
        """
        Initialize bot command handler.

        Args:
            bot_token: Telegram bot token (from BotFather)
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not provided")

        self.subscriber_manager = SubscriberManager()

        # Initialize source registry
        self.source_registry = SourceRegistry()
        self.source_registry.register_source(MeisengeigeScraper)
        self.source_registry.register_source(FilmhausScraper)

        self.application = None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /start command - subscribe to notifications.

        Args:
            update: Telegram update object
            context: Bot context
        """
        chat_id = update.effective_chat.id
        user = update.effective_user
        args = context.args

        if args and len(args) > 0:
            # Direct source specified: /start meisengeige
            source_id = args[0]
            if not self.source_registry.has_source(source_id):
                await update.message.reply_text(
                    f"❌ Unknown source: {source_id}\n\n"
                    "Use /sources to see available sources."
                )
                return

            source = self.source_registry.get_source(source_id)
            if self.subscriber_manager.add_subscription(chat_id, source_id):
                message = f"✅ Subscribed to {source.display_name}!"
            else:
                message = f"ℹ️ Already subscribed to {source.display_name}"

            await update.message.reply_text(message)
        else:
            # Show interactive keyboard with available sources
            keyboard = []
            for source in self.source_registry.list_sources():
                keyboard.append([
                    InlineKeyboardButton(
                        source.display_name,
                        callback_data=f"subscribe:{source.source_id}"
                    )
                ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"🎬 Welcome, {user.first_name}!\n\n"
                "Choose cinema sources to subscribe to:",
                reply_markup=reply_markup
            )

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /stop command - unsubscribe from notifications.

        Args:
            update: Telegram update object
            context: Bot context
        """
        chat_id = update.effective_chat.id
        args = context.args

        if args and len(args) > 0:
            # Direct source specified: /stop meisengeige
            source_id = args[0]
            if not self.source_registry.has_source(source_id):
                await update.message.reply_text(f"❌ Unknown source: {source_id}")
                return

            source = self.source_registry.get_source(source_id)
            if self.subscriber_manager.remove_subscription(chat_id, source_id):
                message = f"✅ Unsubscribed from {source.display_name}"
            else:
                message = f"ℹ️ Not subscribed to {source.display_name}"

            await update.message.reply_text(message)
        else:
            # Show interactive keyboard with user's subscriptions
            user_sources = self.subscriber_manager.get_user_sources(chat_id)

            if not user_sources:
                await update.message.reply_text(
                    "ℹ️ Not subscribed to any sources.\n\n"
                    "Use /start to subscribe."
                )
                return

            keyboard = []
            for source_id in user_sources:
                source = self.source_registry.get_source(source_id)
                keyboard.append([
                    InlineKeyboardButton(
                        f"❌ {source.display_name}",
                        callback_data=f"unsubscribe:{source.source_id}"
                    )
                ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Choose a source to unsubscribe from:",
                reply_markup=reply_markup
            )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /status command - show subscription status.

        Args:
            update: Telegram update object
            context: Bot context
        """
        chat_id = update.effective_chat.id
        user_sources = self.subscriber_manager.get_user_sources(chat_id)

        if not user_sources:
            message = (
                "❌ <b>Not Subscribed</b>\n\n"
                "You're not receiving notifications.\n\n"
                "Use /start to subscribe."
            )
        else:
            lines = ["✅ <b>Active Subscriptions</b>\n"]
            for source_id in user_sources:
                source = self.source_registry.get_source(source_id)
                lines.append(f"• {source.display_name}")

            lines.append("\n<b>Subscriber Counts:</b>")
            for source_id in user_sources:
                source = self.source_registry.get_source(source_id)
                count = self.subscriber_manager.get_subscriber_count(source_id)
                lines.append(f"• {source.display_name}: {count}")

            lines.append("\nUse /stop to unsubscribe")
            message = "\n".join(lines)

        await update.message.reply_text(message, parse_mode='HTML')

    async def sources_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /sources command - list available sources.

        Args:
            update: Telegram update object
            context: Bot context
        """
        lines = ["🎬 <b>Available Cinema Sources</b>\n"]

        for source in self.source_registry.list_sources():
            lines.append(f"<b>{source.display_name}</b>")
            lines.append(f"🔗 {source.url}\n")

        lines.append("Use /start to subscribe to a source")
        message = "\n".join(lines)

        await update.message.reply_text(message, parse_mode='HTML')

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle callback queries from inline keyboards.

        Args:
            update: Telegram update object
            context: Bot context
        """
        query = update.callback_query
        await query.answer()

        chat_id = query.from_user.id
        data = query.data

        if data.startswith("subscribe:"):
            source_id = data.split(":", 1)[1]
            if not self.source_registry.has_source(source_id):
                await query.edit_message_text("❌ Unknown source")
                return

            source = self.source_registry.get_source(source_id)
            if self.subscriber_manager.add_subscription(chat_id, source_id):
                message = (
                    f"✅ Subscribed to {source.display_name}!\n\n"
                    "You'll receive updates for this cinema.\n\n"
                    "Use /start to subscribe to more sources or /status to see all your subscriptions."
                )
            else:
                message = f"ℹ️ Already subscribed to {source.display_name}"

            await query.edit_message_text(message)

        elif data.startswith("unsubscribe:"):
            source_id = data.split(":", 1)[1]
            source = self.source_registry.get_source(source_id)
            if self.subscriber_manager.remove_subscription(chat_id, source_id):
                message = f"✅ Unsubscribed from {source.display_name}"
            else:
                message = f"ℹ️ Not subscribed to {source.display_name}"

            await query.edit_message_text(message)

    def setup_handlers(self) -> Application:
        """
        Set up command handlers and return application.

        Returns:
            Configured Application instance
        """
        self.application = Application.builder().token(self.bot_token).build()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("sources", self.sources_command))

        # Add callback handler for inline keyboards
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))

        return self.application

    async def run(self) -> None:
        """Run the bot in polling mode."""
        if not self.application:
            self.setup_handlers()

        print("🤖 Bot started. Press Ctrl+C to stop.")

        # Initialize and start
        async with self.application:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

            # Keep running
            try:
                import asyncio
                await asyncio.Event().wait()
            except (KeyboardInterrupt, SystemExit):
                pass
            finally:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
