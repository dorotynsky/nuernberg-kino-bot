"""Main script for Meisengeige cinema program monitoring."""

import asyncio
import sys
from typing import Optional
from dotenv import load_dotenv

from .scraper import MeisengeigeScraper
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
    Main monitoring function.

    Args:
        notify: Whether to send Telegram notifications
        storage_dir: Directory to store state files
        bot_token: Telegram bot token (optional, can use env var)
        chat_id: Telegram chat ID (optional, can use env var)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        print("🎬 Starting Meisengeige program monitoring...")

        # Initialize components
        storage = Storage(storage_dir=storage_dir)

        print("📥 Fetching current program...")
        with MeisengeigeScraper() as scraper:
            current_films = scraper.scrape()

        print(f"✅ Found {len(current_films)} films")

        # Load previous snapshot
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
            print("\n🔔 Changes detected:")
            if new_films:
                print(f"  ✨ {len(new_films)} new film(s)")
            if updated_films:
                print(f"  🔄 {len(updated_films)} updated film(s)")
            if removed_films:
                print(f"  ❌ {len(removed_films)} removed film(s)")

            # Send notification if enabled
            if notify:
                print("\n📤 Sending Telegram notification...")
                try:
                    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
                    await notifier.send_update_notification(
                        new_films, removed_films, updated_films
                    )
                    print("✅ Notification sent")
                except Exception as e:
                    print(f"❌ Failed to send notification: {e}")
                    # Don't fail the whole script if notification fails
        else:
            print("\nℹ️  No changes detected")

        # Save current snapshot
        print("\n💾 Saving current snapshot...")
        storage.save_snapshot(current_films)
        print("✅ Snapshot saved")

        print("\n✨ Monitoring complete!")
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
