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

        # Find event cards - they have 'kachel' class
        cards = soup.find_all('div', class_='kachel')

        films = []
        for card in cards:
            film = self._parse_single_event(card)
            if film:
                films.append(film)

        return films

    def _parse_single_event(self, card) -> Optional[Film]:
        """
        Parse a single event from its container element.
        Fetches detail page for enriched information.

        Args:
            card: BeautifulSoup element containing event data

        Returns:
            Film object or None if parsing fails
        """
        try:
            # Extract title and detail URL from detailLink
            title_link = card.find('a', class_='detailLink')
            if not title_link:
                return None
            title = title_link.get_text(strip=True)
            detail_url = title_link.get('href')

            # Extract poster image
            poster_url = None
            img = card.find('img')
            if img and img.get('src'):
                poster_url = img['src']
                if not poster_url.startswith('http'):
                    poster_url = (
                        f"https://www.kunstkulturquartier.de{poster_url}"
                        if poster_url.startswith('/')
                        else poster_url
                    )

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

            # Fetch detail page for enriched information
            description = None
            fsk_rating = None
            duration = None
            genres = ["Kinderkino"]

            if detail_url:
                try:
                    full_detail_url = (
                        f"https://www.kunstkulturquartier.de{detail_url}"
                        if detail_url.startswith('/')
                        else detail_url
                    )
                    detail_info = self._fetch_detail(full_detail_url)
                    if detail_info:
                        description = detail_info.get('description')
                        fsk_rating = detail_info.get('fsk_rating')
                        duration = detail_info.get('duration')
                        if detail_info.get('genre'):
                            genres = [detail_info['genre'], "Kinderkino"]
                except Exception as e:
                    print(f"Warning: Failed to fetch detail for {title}: {e}")

            return Film(
                title=title,
                genres=genres,
                fsk_rating=fsk_rating,
                duration=duration,
                description=description,
                poster_url=poster_url,
                film_id=None,
                showtimes=showtimes,
            )

        except Exception as e:
            print(f"Error parsing Kinderkino event: {e}")
            return None

    def _fetch_detail(self, detail_url: str) -> Optional[dict]:
        """
        Fetch and parse Kinderkino detail page for additional film information.

        Args:
            detail_url: Full URL to the detail page

        Returns:
            Dictionary with film details or None if parsing fails
        """
        try:
            response = self.client.get(detail_url, follow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            main_content = soup.find('main')
            if not main_content:
                return None

            # Extract full description (first paragraph that's not pricing)
            description = None
            for p in main_content.find_all('p'):
                text = p.get_text(strip=True)
                if text and 'Eintritt' not in text and len(text) > 50:
                    description = text
                    break

            # Parse all metadata from the text
            all_text = main_content.get_text() if main_content else ''

            # Extract duration
            duration = None
            duration_match = re.search(r'Länge:\s*(\d+)\s*Min', all_text, re.IGNORECASE)
            if duration_match:
                duration = int(duration_match.group(1))

            # Extract FSK rating
            fsk_rating = None
            fsk_match = re.search(r'FSK:\s*ab\s*(\d+)', all_text, re.IGNORECASE)
            if fsk_match:
                age = fsk_match.group(1)
                fsk_rating = f"FSK: {age}"

            # Extract genre
            genre = None
            genre_match = re.search(
                r'(Animation|Dokumentarfilm|Drama|Komödie|Thriller|Action|Fantasy|Abenteuer)'
                r'(?:\s|Land:|Länge:|$)',
                all_text,
                re.IGNORECASE,
            )
            if genre_match:
                genre = genre_match.group(1)

            # Extract country
            country = None
            country_match = re.search(r'Land:\s*([^\n]+?)(?:Jahr:|Regie:|$)', all_text, re.IGNORECASE)
            if country_match:
                country = country_match.group(1).strip()

            # Extract year
            year = None
            year_match = re.search(r'Jahr:\s*(\d{4})', all_text)
            if year_match:
                year = year_match.group(1)

            # Extract director
            director = None
            director_match = re.search(
                r'Regie:\s*([^\n]+?)(?:Animation|Länge:|Sprache:|$)', all_text, re.IGNORECASE
            )
            if director_match:
                director = director_match.group(1).strip()

            return {
                'description': description,
                'duration': duration,
                'fsk_rating': fsk_rating,
                'genre': genre,
                'country': country,
                'year': year,
                'director': director,
            }

        except Exception as e:
            print(f"Error fetching detail page {detail_url}: {e}")
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
                language=None,
            )
        except Exception as e:
            print(f"Error parsing datetime '{text}': {e}")
            return None
