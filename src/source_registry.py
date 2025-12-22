"""Registry for managing cinema sources."""

from dataclasses import dataclass
from typing import Dict, List, Type

from .base_scraper import BaseCinemaScraper


@dataclass
class SourceInfo:
    """Information about a cinema source."""

    source_id: str
    display_name: str
    url: str
    scraper_class: Type[BaseCinemaScraper]


class SourceRegistry:
    """Registry for managing available cinema sources."""

    def __init__(self):
        """Initialize empty registry."""
        self._sources: Dict[str, SourceInfo] = {}

    def register_source(self, scraper_class: Type[BaseCinemaScraper]) -> None:
        """
        Register a cinema source.

        Args:
            scraper_class: Scraper class to register
        """
        # Create temporary instance to get metadata
        instance = scraper_class()
        info = SourceInfo(
            source_id=instance.get_source_id(),
            display_name=instance.get_display_name(),
            url=instance.get_url(),
            scraper_class=scraper_class
        )
        self._sources[info.source_id] = info
        instance.client.close()

    def get_source(self, source_id: str) -> SourceInfo:
        """
        Get source information by ID.

        Args:
            source_id: Source identifier

        Returns:
            SourceInfo object

        Raises:
            KeyError: If source not found
        """
        return self._sources[source_id]

    def list_sources(self) -> List[SourceInfo]:
        """
        Get list of all registered sources.

        Returns:
            List of SourceInfo objects
        """
        return list(self._sources.values())

    def get_scraper(self, source_id: str) -> BaseCinemaScraper:
        """
        Create and return a scraper instance for the source.

        Args:
            source_id: Source identifier

        Returns:
            Scraper instance

        Raises:
            KeyError: If source not found
        """
        return self._sources[source_id].scraper_class()

    def has_source(self, source_id: str) -> bool:
        """
        Check if source is registered.

        Args:
            source_id: Source identifier

        Returns:
            True if source exists
        """
        return source_id in self._sources
