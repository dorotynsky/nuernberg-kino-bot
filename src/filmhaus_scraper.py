"""Web scraper for Filmhaus Kinderkino program."""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base_scraper import BaseCinemaScraper
from .models import Film, Showtime


class FilmhausScraper(BaseCinemaScraper):
    """Scraper for Filmhaus Kinderkino program page."""

    BASE_URL = "https://www.kunstkulturquartier.de/filmhaus/programm/kinderkino"

    def get_source_id(self) -> str:
        """Return unique source identifier."""
        return "kinderkino"

    def get_display_name(self) -> str:
        """Return human-readable display name."""
        return "Kinderkino (Filmhaus)"

    def get_url(self) -> str:
        """Return program page URL."""
        return self.BASE_URL

    def scrape(self) -> List[Film]:
        """
        Scrape the Kinderkino program page and return list of films.

        Returns:
            List of Film objects

        Raises:
            httpx.HTTPError: If request fails
        """
        response = self.client.get(self.BASE_URL)
        response.raise_for_status()
        return self.parse_films(response.text)

    def parse_films(self, html: str) -> List[Film]:
        """
        Parse films from HTML content.

        Args:
            html: HTML content as string

        Returns:
            List of Film objects
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Find event cards with vkList class
        cards = soup.find_all('div', class_='vkList')

        films = []
        for card in cards:
            film = self._parse_single_event(card)
            if film:
                films.append(film)

        return films

    def _parse_single_event(self, card) -> Optional[Film]:
        """
        Parse a single event from its container element.

        Args:
            card: BeautifulSoup element containing event data

        Returns:
            Film object or None if parsing fails
        """
        try:
            # Extract title from detailLink
            title_link = card.find('a', class_='detailLink')
            if not title_link:
                return None
            title = title_link.get_text(strip=True)

            # Extract poster image
            poster_url = None
            img = card.find('img')
            if img and img.get('src'):
                poster_url = img['src']
                if not poster_url.startswith('http'):
                    poster_url = f"https://www.kunstkulturquartier.de{poster_url}"

            # Extract date/time and venue information
            date_time_text = None
            venue = "Filmhaus Nürnberg"

            # Look for text containing date pattern (e.g., "Mo / 22.12.2025 / 15:00 Uhr")
            for text_elem in card.find_all(string=True):
                text = text_elem.strip()
                if re.search(r'\d{2}\.\d{2}\.\d{4}', text):
                    date_time_text = text
                    break

            # Try to extract venue more precisely if available
            venue_div = card.find('div', string=re.compile(r'Filmhaus'))
            if venue_div:
                venue_text = venue_div.get_text(strip=True)
                if venue_text:
                    venue = venue_text

            showtimes = []
            if date_time_text:
                showtime = self._parse_datetime(date_time_text, venue)
                if showtime:
                    showtimes.append(showtime)

            # Extract description if available
            description = None
            desc_elem = card.find('p')
            if desc_elem:
                description = desc_elem.get_text(strip=True)

            # All events from this page are Kinderkino category
            return Film(
                title=title,
                genres=["Kinderkino"],  # Category
                fsk_rating=None,  # Parse if available in description
                duration=None,  # Parse if available in description
                description=description,
                poster_url=poster_url,
                film_id=None,
                showtimes=showtimes,
            )

        except Exception as e:
            print(f"Error parsing Kinderkino event: {e}")
            return None

    def _parse_datetime(self, text: str, venue: str) -> Optional[Showtime]:
        """
        Parse date/time from Filmhaus format.

        Args:
            text: Date/time string (e.g., 'Mo / 22.12.2025 / 15:00 Uhr')
            venue: Venue name

        Returns:
            Showtime object or None if parsing fails
        """
        try:
            # Extract components: day / DD.MM.YYYY / HH:MM Uhr
            match = re.search(r'(\w+)\s*/\s*(\d{2}\.\d{2}\.?\d*)\s*/\s*(\d{2}:\d{2})', text)
            if not match:
                return None

            day_of_week, date_str, time_str = match.groups()

            # Convert date format to match Meisengeige format
            # From "22.12.2025" to "Mo.22.12"
            date_parts = date_str.split('.')
            if len(date_parts) >= 2:
                formatted_date = f"{day_of_week}.{date_parts[0]}.{date_parts[1]}"
            else:
                formatted_date = f"{day_of_week}.{date_str}"

            return Showtime(
                date=formatted_date,
                time=time_str,
                room=venue,
                language=None,  # Can be parsed if available
            )
        except Exception as e:
            print(f"Error parsing datetime '{text}': {e}")
            return None
