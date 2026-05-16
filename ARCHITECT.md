# IchikaBot Architecture & Contribution Guide

Welcome to the IchikaBot source code! This document provides an overview of the bot's internal architecture, file structure, and module dependencies. It is intended for developers who wish to understand or contribute to the project.

## 🏗️ Architecture Overview

IchikaBot is built using `discord.py` and follows a modular **Cog-based architecture**. This means each major feature is encapsulated in its own class (a "Cog") within the `cogs/` directory.

To ensure performance and low RAM usage, the bot heavily utilizes the **Singleton pattern** for loading large game data files (like thousands of cards or character details). Persistent data (such as user gacha pity or persistent UI states) is stored via an async SQLite database.

---

## 📂 Core Components & Utilities (`utils/`)

The `utils/` directory acts as the backbone of the bot. Cogs should rely on these utilities rather than loading raw JSON/data themselves.

### `utils/card_data.py` (CardDataManager)
- **Role**: Singleton that parses and holds all card data (`cards.json`) in memory once. It pre-computes rarity pools and EN prefixes to drastically reduce memory usage.
- **Depended on by**: `cogs/card.py`, `cogs/gacha.py`, `cogs/guess.py`, `cogs/birthday.py`, `cogs/profile.py`, `cogs/card_of_day.py`, `cogs/tournament.py`, `cogs/data_updater.py`.

### `utils/game_data.py` (GameDataManager)
- **Role**: Singleton that manages character and nickname data.
- **Depended on by**: `cogs/guess.py`, `cogs/birthday.py`, `cogs/tournament.py`.

### `utils/database.py` (Async SQLite Layer)
- **Role**: Handles all database interactions (`ichika.db`) asynchronously using `aiosqlite`. Manages tables for gacha pity, persistent streaming embeds, etc.
- **Depended on by**: `cogs/gacha.py`, `cogs/streaming.py`, `bot.py` (for initialization).

### Other Utilities
- `utils/autoupdater.py`: Fetches the latest game data and assets from external sources.
- `utils/cards.py` & `utils/image_helper.py`: Image manipulation (cropping, compositing) for gacha pulls and card guessing hints.
- `utils/romaji.py`: Search normalization for Japanese/Romaji queries.

---

## 🧩 Features & Modules (`cogs/`)

Each file in `cogs/` is a self-contained feature module loaded by `bot.py` on startup.

| Module | Feature Description | Key Dependencies |
|--------|---------------------|------------------|
| `streaming.py` | YouTube audio player with queue, loops, volume control, and persistent Now-Playing UI. | `yt-dlp`, FFmpeg, `utils.database` |
| `music.py` | Audio guessing minigame with time limits and difficulty modifiers (speedup/reverse). | `song.xlsx`, `pydub`, FFmpeg |
| `tournament.py` | 5-round card guessing tournament with progressive visual hints (grayscale -> colour -> full). | `utils.card_data`, `utils.game_data` |
| `guess.py` | Single-round quick card guessing minigame. | `utils.card_data`, `utils.game_data` |
| `gacha.py` | Gacha simulator with rarity pools and pity system. | `utils.card_data`, `utils.database` |
| `card.py` | Search and display high-res card artwork. | `utils.card_data` |
| `card_of_day.py` | Scheduled daily random card announcements per guild. | `utils.card_data` |
| `birthday.py` | Automated character birthday announcements. | `utils.card_data`, `utils.game_data` |
| `profile.py` | Detailed character profile lookups. | `utils.card_data` |
| `songs.py` | Song database lookup (BPM, difficulties, duration). | Static music JSONs, `utils.romaji` |
| `events.py` | Current and upcoming event tracking. | Static event JSONs |
| `mercari.py` | Mercari JP lookup with JPY to VND conversion. | External API scraping |
| `data_updater.py`| Scheduled job that triggers `utils/autoupdater.py` to refresh local game data. | `utils.autoupdater`, `utils.card_data` (for reloading) |

---

## 🔄 Data Flow Example: Updating Game Assets

1. `cogs/data_updater.py` runs its scheduled task.
2. It calls `utils/autoupdater.py` to fetch new JSONs/images from GitHub or API sources.
3. If `cards.json` changes, it calls `CardDataManager.reload()` in `utils/card_data.py`.
4. All cogs (like `gacha.py` or `card.py`) instantly have access to the new cards without needing to restart the bot or reload their own files, ensuring zero downtime and preventing RAM spikes.

---

## 🛠️ Contribution Guidelines

1. **Memory Management**: Never use `json.load(open('cards.json'))` inside a cog. Always import the singleton from `utils.card_data` or `utils.game_data`.
2. **Database**: Do not write local `.json` files for persistent state (e.g., user settings). Add a new table schema to `utils/database.py` and use `aiosqlite`.
3. **Blocking Operations**: IchikaBot is fully async. Any heavy CPU task (like `pydub` image/audio processing in `music.py` or `cards.py`) must be run via `await bot.loop.run_in_executor()`.
4. **Commands**: Prefer slash commands (`@app_commands.command()`) for new features, but prefix command aliases are acceptable for quick-access minigames (like `!play` or `!sg`).
