"""Data models for cinema program."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Showtime:
    """Represents a single film showtime."""

    date: str  # Format: "Mo. 15.12"
    time: str  # Format: "20:30"
    room: str  # e.g., "Kino 2"
    language: Optional[str] = None  # e.g., "OV", "OmU"

    def __str__(self) -> str:
        """Human-readable representation."""
        lang_info = f" ({self.language})" if self.language else ""
        return f"{self.date} {self.time} - {self.room}{lang_info}"


@dataclass
class Film:
    """Represents a film with all its information."""

    title: str
    genres: List[str] = field(default_factory=list)
    fsk_rating: Optional[str] = None
    duration: Optional[int] = None  # in minutes
    description: Optional[str] = None
    poster_url: Optional[str] = None
    showtimes: List[Showtime] = field(default_factory=list)
    film_id: Optional[str] = None  # Unique ID from webpage

    def __str__(self) -> str:
        """Human-readable representation."""
        genres_str = ", ".join(self.genres) if self.genres else "No genres"
        duration_str = f"{self.duration}min" if self.duration else "N/A"
        fsk_str = self.fsk_rating or "N/A"
        return f"{self.title} ({genres_str}, {duration_str}, {fsk_str})"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "title": self.title,
            "genres": self.genres,
            "fsk_rating": self.fsk_rating,
            "duration": self.duration,
            "description": self.description,
            "poster_url": self.poster_url,
            "film_id": self.film_id,
            "showtimes": [
                {
                    "date": st.date,
                    "time": st.time,
                    "room": st.room,
                    "language": st.language,
                }
                for st in self.showtimes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Film":
        """Create Film instance from dictionary."""
        showtimes = [
            Showtime(
                date=st["date"],
                time=st["time"],
                room=st["room"],
                language=st.get("language"),
            )
            for st in data.get("showtimes", [])
        ]

        return cls(
            title=data["title"],
            genres=data.get("genres", []),
            fsk_rating=data.get("fsk_rating"),
            duration=data.get("duration"),
            description=data.get("description"),
            poster_url=data.get("poster_url"),
            film_id=data.get("film_id"),
            showtimes=showtimes,
        )


@dataclass
class ProgramSnapshot:
    """Represents a snapshot of the cinema program at a point in time."""

    timestamp: str
    films: List[Film] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "films": [film.to_dict() for film in self.films],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramSnapshot":
        """Create ProgramSnapshot instance from dictionary."""
        films = [Film.from_dict(film_data) for film_data in data.get("films", [])]
        return cls(
            timestamp=data["timestamp"],
            films=films,
        )
