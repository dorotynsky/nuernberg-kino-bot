"""Web scraper for Meisengeige cinema program."""

import re
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup

from .models import Film, Showtime


class MeisengeigeScraper:
    """Scraper for Meisengeige cinema program page."""

    BASE_URL = "https://www.cinecitta.de/programm/meisengeige/"
    TIMEOUT = 30.0

    def __init__(self):
        """Initialize the scraper."""
        self.client = httpx.Client(timeout=self.TIMEOUT)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close HTTP client."""
        self.client.close()

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

        # Get dates from header
        dates = []
        header_row = table.find('thead')
        if header_row:
            date_cells = header_row.find_all('th')
            for cell in date_cells:
                date_text = cell.text.strip()
                if date_text and date_text != '':
                    # Format: "Mo. 15.12"
                    dates.append(date_text)

        # Parse rows (each row is a room)
        tbody = table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
            for row in rows:
                # Get room name from first cell
                room_cell = row.find('td')
                room = room_cell.text.strip() if room_cell else "Unknown"

                # Get language if present (OV, OmU, etc.)
                language = None
                lang_elem = row.find('span', class_=re.compile('language|OV|OmU'))
                if lang_elem:
                    language = lang_elem.text.strip()

                # Get times from other cells
                time_cells = row.find_all('td')[1:]  # Skip first cell (room name)

                for idx, cell in enumerate(time_cells):
                    time_text = cell.text.strip()
                    if time_text and re.match(r'\d{1,2}:\d{2}', time_text):
                        date = dates[idx] if idx < len(dates) else "Unknown"
                        showtimes.append(
                            Showtime(
                                date=date,
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
