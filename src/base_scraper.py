"""Base class for cinema program scrapers."""

from abc import ABC, abstractmethod
from typing import List
import httpx

from .models import Film


class BaseCinemaScraper(ABC):
    """Abstract base class for all cinema scrapers."""

    TIMEOUT = 30.0

    def __init__(self):
        """Initialize the scraper with HTTP client."""
        self.client = httpx.Client(timeout=self.TIMEOUT)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close HTTP client."""
        self.client.close()

    @abstractmethod
    def get_source_id(self) -> str:
        """
        Return unique source identifier.

        Returns:
            Source ID (e.g., 'meisengeige', 'kinderkino')
        """
        pass

    @abstractmethod
    def get_display_name(self) -> str:
        """
        Return human-readable display name.

        Returns:
            Display name (e.g., 'Meisengeige', 'Kinderkino (Filmhaus)')
        """
        pass

    @abstractmethod
    def get_url(self) -> str:
        """
        Return program page URL.

        Returns:
            URL of the cinema program page
        """
        pass

    @abstractmethod
    def scrape(self) -> List[Film]:
        """
        Scrape and return films from source.

        Returns:
            List of Film objects

        Raises:
            httpx.HTTPError: If request fails
        """
        pass
