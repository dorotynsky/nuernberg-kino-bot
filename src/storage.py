"""Storage for cinema program snapshots."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

from .models import ProgramSnapshot, Film


class Storage:
    """Handles saving and loading program snapshots."""

    def __init__(self, storage_dir: str = "state"):
        """
        Initialize storage.

        Args:
            storage_dir: Directory to store state files
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.snapshot_file = self.storage_dir / "latest_snapshot.json"

    def save_snapshot(self, films: List[Film]) -> None:
        """
        Save current program snapshot to file.

        Args:
            films: List of films to save
        """
        snapshot = ProgramSnapshot(
            timestamp=datetime.now().isoformat(),
            films=films,
        )

        with open(self.snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)

    def load_snapshot(self) -> Optional[ProgramSnapshot]:
        """
        Load the latest program snapshot from file.

        Returns:
            ProgramSnapshot or None if file doesn't exist
        """
        if not self.snapshot_file.exists():
            return None

        try:
            with open(self.snapshot_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return ProgramSnapshot.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading snapshot: {e}")
            return None

    def compare_snapshots(
        self, old_snapshot: Optional[ProgramSnapshot], new_films: List[Film]
    ) -> Tuple[List[Film], List[Film], List[Film]]:
        """
        Compare old and new snapshots to detect changes.

        Args:
            old_snapshot: Previous snapshot (can be None)
            new_films: List of current films

        Returns:
            Tuple of (new_films, removed_films, updated_films)
        """
        if not old_snapshot:
            # First run - all films are "new"
            return new_films, [], []

        old_films_dict = {film.title: film for film in old_snapshot.films}
        new_films_dict = {film.title: film for film in new_films}

        # Find new films
        new_film_titles = set(new_films_dict.keys()) - set(old_films_dict.keys())
        new = [new_films_dict[title] for title in new_film_titles]

        # Find removed films
        removed_film_titles = set(old_films_dict.keys()) - set(new_films_dict.keys())
        removed = [old_films_dict[title] for title in removed_film_titles]

        # Find updated films (same title but different showtimes or other data)
        updated = []
        for title in set(old_films_dict.keys()) & set(new_films_dict.keys()):
            old_film = old_films_dict[title]
            new_film = new_films_dict[title]

            if self._film_changed(old_film, new_film):
                updated.append(new_film)

        return new, removed, updated

    def _film_changed(self, old_film: Film, new_film: Film) -> bool:
        """
        Check if a film has changed between snapshots.

        Args:
            old_film: Previous film data
            new_film: Current film data

        Returns:
            True if film has changed
        """
        # Compare key attributes
        if old_film.description != new_film.description:
            return True

        # Compare showtimes
        old_showtimes = set(
            (st.date, st.time, st.room, st.language) for st in old_film.showtimes
        )
        new_showtimes = set(
            (st.date, st.time, st.room, st.language) for st in new_film.showtimes
        )

        return old_showtimes != new_showtimes
