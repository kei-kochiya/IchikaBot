# IchikaBot Architecture & Contribution Guide

Welcome to the IchikaBot source code! This document provides an overview of the bot's internal architecture, file structure, and module dependencies. It is intended for developers who wish to understand or contribute to the project.

## 🏗️ Architecture Overview

IchikaBot is built using `discord.py` and follows a modular **Cog-based architecture**. Each major feature is encapsulated in its own class (a "Cog") within organized subdirectories under `cogs/`.

To ensure performance and low RAM usage, the bot heavily utilizes the **Singleton pattern** for loading large game data files. Persistent data is stored via an async SQLite database. Logic is cleanly separated between the presentation layer (`cogs/`) and the core logic/UI layer (`utils/`).

---

## 📂 Utilities & Core Logic (`utils/`)

The `utils/` directory acts as the backbone of the bot. Cogs should rely on these utilities rather than implementing complex logic or loading raw JSON data themselves.

### `utils/data/` (Data Management)
- **`game_data.py`**: Singleton that manages character and nickname data.
- **`card_data.py`**: Singleton that parses and holds all card data (`cards.json`) in memory.
- **`music_quiz_db.py`**: Database class for the `song.xlsx` used in the music guessing minigame.
- **Depended on by**: Almost all game and info cogs (e.g., `birthday.py`, `tournament.py`, `profile.py`, `card.py`).

### `utils/core/` (System Core)
- **`database.py`**: Handles all asynchronous interactions with `ichika.db`. Used heavily by `gacha.py` and `streaming.py`.
- **`autoupdater.py`**: Fetches and syncs new assets/data from upstream sources.
- **`romaji.py`**: Normalization and romaji conversion logic for search features.

### `utils/media/` (Media Processing)
- **`image_helper.py`**: Asynchronous image caching and fetching.
- **`audio_fx.py`**: Audio manipulation logic (FFmpeg/Pydub).

### Domain-Specific Helpers
- **`utils/game/`**: Logic and UI components for minigames (`tournament_logic.py`, `tournament_ui.py`, `cards.py`).
- **`utils/social/`**: Date calculations and Embed generation for social features (`birthday_helpers.py`, `birthday_ui.py`).
- **`utils/info/`**: Shared Embed generation and Pagination Views (`songs_ui.py`, `events_ui.py`).
- **`utils/voice/`**: Streaming player models, YouTube downloader logic (`yt-dlp`), and UI (`NowPlayingView`).

---

## 🧩 Features & Modules (`cogs/`)

Cogs are organized into subdirectories by category. The bot recursively loads all `.py` files in this tree.

| Module Area | Feature Description | Key Dependencies |
|:---|:---|:---|
| **`cogs/voice/`** | Music and audio streaming features. | `utils.voice.*`, `utils.media.audio_fx` |
| **`cogs/game/`** | Minigames (Tournament, Guess, Gacha). | `utils.data.*`, `utils.game.*` |
| **`cogs/info/`** | Database lookups (Cards, Profiles, Songs, Events). | `utils.info.*`, `utils.core.romaji` |
| **`cogs/social/`** | Server engagement features (Birthdays, Card of the Day). | `utils.social.*`, `utils.data.*` |
| **`cogs/system/`** | Bot administration (Data Auto-updater, Help). | `utils.core.autoupdater` |
| **`cogs/misc/`** | Miscellaneous tools (Mercari JP search). | External APIs |

---

## 🔄 Data Flow Example: Updating Game Assets

1. `cogs/system/data_updater.py` runs its scheduled task.
2. It calls `utils/core/autoupdater.py` to fetch new assets.
3. If `cards.json` changes, it calls `CardDataManager.reload()` via `utils/data/card_data.py`.
4. All cogs instantly access the new data via the Singleton references without requiring a bot restart.

---

## 🛠️ Contribution Guidelines

1. **Memory**: Use singletons from `utils.data` instead of manually loading JSONs.
2. **Separation of Concerns**: Keep Cogs small. Move Embed generation, Pagination UI, and complex calculations to the corresponding `utils/` subdirectory.
3. **Persistence**: Use `utils.core.database.py` schema for new user data.
4. **Async Execution**: Heavy tasks (Pillow/Pydub) must use `await bot.loop.run_in_executor()`.
