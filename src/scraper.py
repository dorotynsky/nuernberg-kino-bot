"""Web scraper for Meisengeige cinema program."""

import re
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup

from .models import Film, Showtime
from .base_scraper import BaseCinemaScraper


class MeisengeigeScraper(BaseCinemaScraper):
    """Scraper for Meisengeige cinema program page."""

    BASE_URL = "https://www.cinecitta.de/programm/meisengeige/"

    def get_source_id(self) -> str:
        """Return unique source identifier."""
        return "meisengeige"

    def get_display_name(self) -> str:
        """Return human-readable display name."""
        return "Meisengeige"

    def get_url(self) -> str:
        """Return program page URL."""
        return self.BASE_URL

    def fetch_page(self) -> str:
        """
        Fetch the Meisengeige program page.

        Returns:
            HTML content as string

        Raises:
            httpx.HTTPError: If request fails
        """
        response = self.client.get(self.BASE_URL)
        response.raise_for_status()
        return response.text

    def parse_films(self, html: str) -> List[Film]:
        """
        Parse films from HTML content.

        Args:
            html: HTML content as string

        Returns:
            List of Film objects
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Find all film containers
        film_containers = soup.find_all('li', class_='filmapi-container__list--li')

        films = []
        for container in film_containers:
            film = self._parse_single_film(container)
            if film:
                films.append(film)

        return films

    def _parse_single_film(self, container) -> Optional[Film]:
        """
        Parse a single film from its container element.

        Args:
            container: BeautifulSoup element containing film data

        Returns:
            Film object or None if parsing fails
        """
        try:
            # Extract film ID
            film_id = container.get('id', '').replace('film-', '') if container.get('id') else None

            # Extract title
            title_elem = container.find('h3', class_='text-white')
            title = title_elem.text.strip() if title_elem else None

            if not title:
                return None

            # Extract genres
            genre_elems = container.find_all('span', class_='px-2 bg-petrol-50')
            genres = [genre.text.strip() for genre in genre_elems]

            # Extract FSK rating
            fsk_elem = container.find('span', class_=re.compile('age-rating--'))
            fsk_rating = fsk_elem.text.strip() if fsk_elem else None

            # Extract duration
            duration = None
            duration_elem = container.find('i', class_='icon-clock')
            if duration_elem and duration_elem.parent:
                duration_text = duration_elem.parent.text.strip()
                duration_match = re.search(r'(\d+)\s*min', duration_text)
                if duration_match:
                    duration = int(duration_match.group(1))

            # Extract description
            desc_elem = container.find('p', class_='leading-tight')
            description = desc_elem.text.strip() if desc_elem else None

            # Extract poster URL
            poster_url = None
            img_elem = container.find('img')
            if img_elem and img_elem.get('src'):
                poster_url = img_elem['src']
                if not poster_url.startswith('http'):
                    poster_url = f"https://www.cinecitta.de{poster_url}"

            # Extract showtimes
            showtimes = self._parse_showtimes(container)

            return Film(
                title=title,
                genres=genres,
                fsk_rating=fsk_rating,
                duration=duration,
                description=description,
                poster_url=poster_url,
                film_id=film_id,
                showtimes=showtimes,
            )

        except Exception as e:
            print(f"Error parsing film: {e}")
            return None

    def _parse_showtimes(self, container) -> List[Showtime]:
        """
        Parse showtimes from film container.

        Args:
            container: BeautifulSoup element containing film data

        Returns:
            List of Showtime objects
        """
        showtimes = []

        # Find showtime section
        showtime_section = container.find('div', class_='show_playing_times__content--inner')
        if not showtime_section:
            return showtimes

        # Find the table with showtimes
        table = showtime_section.find('table', class_='film-list-table')
        if not table:
            return showtimes

        # Get dates from header (skip first empty th)
        dates = []
        thead = table.find('thead')
        if thead:
            header_cells = thead.find_all('th')
            # Skip first header (empty column for room/language info)
            for cell in header_cells[1:]:
                date_text = cell.get_text(strip=True)
                if date_text:
                    dates.append(date_text)

        if not dates:
            return showtimes

        # Parse rows
        tbody = table.find('tbody')
        if not tbody:
            return showtimes

        rows = tbody.find_all('tr')
        for row in rows:
            # First element is <th> containing room and language info
            room_header = row.find('th')
            if not room_header:
                continue

            # Extract room name
            room_div = room_header.find('div', class_='font-semibold')
            room = room_div.get_text(strip=True) if room_div else "Unknown"

            # Extract language (OV, OmU, etc.)
            language = None
            lang_div = room_header.find('div', class_='release-types')
            if lang_div:
                lang_span = lang_div.find('span')
                if lang_span:
                    lang_text = lang_span.get_text(strip=True)
                    if lang_text:
                        language = lang_text

            # Get time cells (all <td> elements)
            time_cells = row.find_all('td')

            # Match each time cell with corresponding date
            for idx, cell in enumerate(time_cells):
                if idx >= len(dates):
                    break

                # Look for time link inside cell
                time_link = cell.find('a', class_='performance-link')
                if time_link:
                    time_span = time_link.find('span', class_='link-text')
                    if time_span:
                        time_text = time_span.get_text(strip=True)
                        if time_text and re.match(r'\d{1,2}:\d{2}', time_text):
                            showtimes.append(
                                Showtime(
                                    date=dates[idx],
                                    time=time_text,
                                    room=room,
                                    language=language,
                                )
                            )

        return showtimes

    def scrape(self) -> List[Film]:
        """
        Scrape the Meisengeige program page and return list of films.

        Returns:
            List of Film objects

        Raises:
            httpx.HTTPError: If request fails
        """
        html = self.fetch_page()
        return self.parse_films(html)
