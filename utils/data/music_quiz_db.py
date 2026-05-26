import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
SONG_DB_PATH = Path(__file__).parent.parent.parent / "gameData" / "static" / "song.xlsx"

def normalize(text: str) -> str:
    """
    Keep only alphanumeric characters, strip everything else (including spaces),
    and lowercase. Applied to both song titles and player guesses before comparison.
    """
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

def is_correct_guess(raw_guess: str, norm_targets: list[str]) -> bool:
    """
    Check whether raw_guess matches any of the normalized target strings.
    """
    ng = normalize(raw_guess)
    if not ng:
        return False
    for target in norm_targets:
        if ng == target:
            return True
        if len(ng) >= 3 and ng in target:
            return True
    return False

class MusicQuizDB:
    _instance = None
    _db: dict[str, dict] = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load_db()
        return cls._instance

    def load_db(self) -> None:
        """Load song.xlsx into _db keyed by song index (as string)."""
        if not SONG_DB_PATH.exists():
            logger.warning("MusicQuizDB: song.xlsx not found at %s", SONG_DB_PATH)
            return
        try:
            import openpyxl
            wb = openpyxl.load_workbook(SONG_DB_PATH, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
        except Exception as e:
            logger.error("MusicQuizDB: Failed to load song.xlsx: %s", e)
            return

        if not rows:
            return

        start = 0
        if rows[0][0] is not None and str(rows[0][0]).lower() == 'index':
            start = 1

        db = {}
        for row in rows[start:]:
            if not row or row[0] is None:
                continue
            idx        = str(row[0]).strip()
            title_jp   = str(row[1]).strip() if len(row) > 1 and row[1] else None
            title_en   = str(row[2]).strip() if len(row) > 2 and row[2] else None
            romaji     = str(row[7]).strip() if len(row) > 7 and row[7] else None
            db[idx] = {"title_en": title_en, "romaji_title": romaji, "title_jp": title_jp}

        self._db = db
        logger.info("MusicQuizDB: Loaded %d songs from song.xlsx", len(db))

    def get_song_info(self, filename: str) -> dict:
        idx = os.path.splitext(filename)[0]
        return self._db.get(idx, {"title_en": None, "romaji_title": None, "title_jp": idx})

    @staticmethod
    def build_display_answer(info: dict) -> str:
        parts = []
        if info.get("title_en"):
            parts.append(info["title_en"])
        if info.get("romaji_title") and info["romaji_title"] != info.get("title_en"):
            parts.append(info["romaji_title"])
        if not parts:
            parts.append(info.get("title_jp") or "???")
        return " / ".join(parts)

    @staticmethod
    def build_norm_targets(info: dict) -> list[str]:
        targets = []
        if info.get("title_en"):
            targets.append(normalize(info["title_en"]))
        if info.get("romaji_title"):
            targets.append(normalize(info["romaji_title"]))
        return [t for t in targets if t]

    @staticmethod
    def build_reveal(info: dict) -> str:
        lines = []
        if info.get("title_en"):
            lines.append(f"🎵 **{info['title_en']}**")
        if info.get("romaji_title") and info["romaji_title"] != info.get("title_en"):
            lines.append(f"🔤 *{info['romaji_title']}*")
        if not lines and info.get("title_jp"):
            lines.append(f"🎵 **{info['title_jp']}**")
        return "\n".join(lines) if lines else "???"
