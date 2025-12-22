"""Subscriber management for Telegram notifications."""

import json
from pathlib import Path
from typing import Set, Dict, List, Any, Optional


class SubscriberManager:
    """Manages the list of subscribers for notifications."""

    def __init__(self, storage_file: str = "state/subscribers.json"):
        """
        Initialize subscriber manager.

        Args:
            storage_file: Path to JSON file storing subscribers
        """
        self.storage_file = Path(storage_file)
        self.storage_file.parent.mkdir(exist_ok=True)
        self._subscribers: Dict[int, Dict[str, Any]] = self._load_subscribers()

    def _load_subscribers(self) -> Dict[int, Dict[str, Any]]:
        """
        Load subscribers from storage file.

        Returns:
            Dict mapping chat IDs to subscriber data
        """
        if not self.storage_file.exists():
            return {}

        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return self._migrate_old_format(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error loading subscribers: {e}")
            return {}

    def _migrate_old_format(self, data: dict) -> Dict[int, Dict[str, Any]]:
        """
        Migrate from old Set[int] to new Dict structure.

        Args:
            data: Raw data from JSON file

        Returns:
            Migrated subscriber dictionary
        """
        if isinstance(data.get('subscribers'), list):
            # Old format: {"subscribers": [123, 456]}
            print("Migrating subscribers from old format...")
            migrated = {}
            for chat_id in data['subscribers']:
                migrated[int(chat_id)] = {
                    "sources": ["meisengeige"],  # Default to Meisengeige
                    "language": "en"
                }
            print(f"Migrated {len(migrated)} subscribers to new format")
            return migrated
        # New format: {"subscribers": {"123": {"sources": [...]}}}
        subscribers_dict = data.get('subscribers', {})
        # Convert string keys to integers
        return {int(k): v for k, v in subscribers_dict.items()}

    def _save_subscribers(self) -> None:
        """Save subscribers to storage file."""
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {'subscribers': self._subscribers},
                    f,
                    ensure_ascii=False,
                    indent=2
                )
        except OSError as e:
            print(f"Error saving subscribers: {e}")

    def add_subscription(self, chat_id: int, source_id: str) -> bool:
        """
        Add subscription to specific source.

        Args:
            chat_id: Telegram chat ID
            source_id: Source identifier

        Returns:
            True if subscription was added, False if already exists
        """
        if chat_id not in self._subscribers:
            self._subscribers[chat_id] = {"sources": [], "language": "en"}

        if source_id in self._subscribers[chat_id]["sources"]:
            return False

        self._subscribers[chat_id]["sources"].append(source_id)
        self._save_subscribers()
        return True

    def remove_subscription(self, chat_id: int, source_id: str) -> bool:
        """
        Remove subscription from specific source.

        Args:
            chat_id: Telegram chat ID
            source_id: Source identifier

        Returns:
            True if subscription was removed, False if not found
        """
        if chat_id not in self._subscribers:
            return False

        if source_id not in self._subscribers[chat_id]["sources"]:
            return False

        self._subscribers[chat_id]["sources"].remove(source_id)

        # Remove user entirely if no sources left
        if not self._subscribers[chat_id]["sources"]:
            del self._subscribers[chat_id]

        self._save_subscribers()
        return True

    def get_subscribers_for_source(self, source_id: str) -> Set[int]:
        """
        Get all subscribers for a specific source.

        Args:
            source_id: Source identifier

        Returns:
            Set of chat IDs subscribed to this source
        """
        return {
            chat_id
            for chat_id, data in self._subscribers.items()
            if source_id in data.get("sources", [])
        }

    def get_user_sources(self, chat_id: int) -> List[str]:
        """
        Get list of sources user is subscribed to.

        Args:
            chat_id: Telegram chat ID

        Returns:
            List of source IDs user is subscribed to
        """
        if chat_id not in self._subscribers:
            return []
        return self._subscribers[chat_id].get("sources", [])

    def is_subscribed(self, chat_id: int, source_id: Optional[str] = None) -> bool:
        """
        Check if user is subscribed.

        Args:
            chat_id: Telegram chat ID
            source_id: Optional source identifier. If None, check any subscription.

        Returns:
            True if subscribed
        """
        if chat_id not in self._subscribers:
            return False
        if source_id is None:
            return len(self._subscribers[chat_id].get("sources", [])) > 0
        return source_id in self._subscribers[chat_id].get("sources", [])

    def get_subscriber_count(self, source_id: Optional[str] = None) -> int:
        """
        Get subscriber count.

        Args:
            source_id: Optional source identifier. If None, return total unique users.

        Returns:
            Number of subscribers
        """
        if source_id is None:
            return len(self._subscribers)
        return len(self.get_subscribers_for_source(source_id))

    # Legacy methods for backward compatibility
    def add_subscriber(self, chat_id: int) -> bool:
        """
        Legacy method: Add subscriber to Meisengeige by default.

        Args:
            chat_id: Telegram chat ID

        Returns:
            True if subscriber was added
        """
        return self.add_subscription(chat_id, "meisengeige")

    def remove_subscriber(self, chat_id: int) -> bool:
        """
        Legacy method: Remove all subscriptions.

        Args:
            chat_id: Telegram chat ID

        Returns:
            True if any subscriptions were removed
        """
        if chat_id not in self._subscribers:
            return False

        del self._subscribers[chat_id]
        self._save_subscribers()
        return True

    def get_all_subscribers(self) -> Set[int]:
        """
        Legacy method: Get all subscriber chat IDs.

        Returns:
            Set of chat IDs
        """
        return set(self._subscribers.keys())
