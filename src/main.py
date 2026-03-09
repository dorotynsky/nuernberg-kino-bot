"""Main script for multi-source cinema program monitoring."""

import asyncio
import os
import sys
from typing import Optional
from dotenv import load_dotenv

from .source_registry import SourceRegistry
from .scraper import MeisengeigeScraper
from .filmhaus_scraper import FilmhausScraper
from .storage import Storage
from .notifier import TelegramNotifier

# Load environment variables from .env file
load_dotenv()


async def main(
    notify: bool = True,
    storage_dir: str = "state",
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> int:
    """
    Main monitoring function for all cinema sources.

    Args:
        notify: Whether to send Telegram notifications
        storage_dir: Directory to store state files
        bot_token: Telegram bot token (optional, can use env var)
        chat_id: Telegram chat ID (optional, can use env var)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        print("🎬 Starting multi-source cinema program monitoring...")

        # Initialize source registry
        source_registry = SourceRegistry()
        source_registry.register_source(MeisengeigeScraper)
        source_registry.register_source(FilmhausScraper)

        # Initialize notifier once
        notifier = None
        if notify:
            notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

        # Process each source
        for source_info in source_registry.list_sources():
            print(f"\n📍 Checking {source_info.display_name}...")

            try:
                # Scrape current program
                print("📥 Fetching current program...")
                with source_registry.get_scraper(source_info.source_id) as scraper:
                    current_films = scraper.scrape()

                print(f"✅ Found {len(current_films)} films")

                # Load previous snapshot for this source
                storage = Storage(storage_dir=storage_dir, source_id=source_info.source_id)
                print("📂 Loading previous snapshot...")
                previous_snapshot = storage.load_snapshot()

                if previous_snapshot:
                    print(f"📊 Comparing with previous snapshot from {previous_snapshot.timestamp}")
                else:
                    print("ℹ️  No previous snapshot found (first run)")

                # Compare snapshots
                new_films, removed_films, updated_films = storage.compare_snapshots(
                    previous_snapshot, current_films
                )

                # Report changes
                if new_films or removed_films or updated_films:
                    print(f"\n🔔 Changes detected for {source_info.display_name}:")
                    if new_films:
                        print(f"  ✨ {len(new_films)} new film(s)")
                    if updated_films:
                        print(f"  🔄 {len(updated_films)} updated film(s)")
                    if removed_films:
                        print(f"  ❌ {len(removed_films)} removed film(s)")

                    # Send notification
                    if notifier:
                        print(f"\n📤 Sending Telegram notification for {source_info.display_name}...")
                        try:
                            await notifier.send_update_notification(
                                source_info.source_id,
                                source_info.display_name,
                                source_info.url,
                                new_films,
                                removed_films,
                                updated_films
                            )
                            print("✅ Notification sent")
                        except Exception as e:
                            print(f"❌ Failed to send notification: {e}")
                            # Don't fail if notification fails
                else:
                    print(f"\nℹ️  No changes detected for {source_info.display_name}")

                # Save current snapshot
                print(f"\n💾 Saving current snapshot for {source_info.display_name}...")
                storage.save_snapshot(current_films)
                print("✅ Snapshot saved")

            except Exception as e:
                print(f"❌ Error checking {source_info.display_name}: {e}")
                import traceback
                traceback.print_exc()
                # Continue with other sources

        # Ping MongoDB to prevent Atlas free tier from pausing (60-day inactivity limit)
        try:
            from pymongo import MongoClient
            mongodb_uri = os.getenv('MONGODB_URI')
            if mongodb_uri:
                client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
                client['nuernberg_kino_bot']['subscribers'].find_one()
                print("📡 MongoDB keep-alive ping OK")
        except Exception as e:
            print(f"⚠️  MongoDB ping failed: {e}")

        print("\n✨ Monitoring complete!")
        return 0

    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
