# IchikaBot Architecture & Contribution Guide

Welcome to the IchikaBot source code! This document provides an overview of the bot's internal architecture, file structure, and module dependencies. It is intended for developers who wish to understand or contribute to the project.

## 🏗️ Architecture Overview

IchikaBot is built using `discord.py` and follows a modular **Cog-based architecture**. Each major feature is encapsulated in its own class (a "Cog") within organized subdirectories under `cogs/`.

To ensure performance and low RAM usage, the bot heavily utilizes the **Singleton pattern** for loading large game data files. Persistent data is stored via an async SQLite database. Logic is cleanly separated between the presentation layer (`cogs/`) and the core logic/UI layer (`utils/`).

---

## 📂 Utilities & Core Logic (`utils/`)

The `utils/` directory acts as the backbone of the bot. Cogs should rely on these utilities rather than implementing complex logic or loading raw JSON data themselves.

### `utils/data/` (Data Management)
- **`game_data.py`**: Singleton (`game_data`) managing character definitions, units, colors, profiles, and nicknames.
- **`card_data.py`**: Singleton (`card_data`) that parses and caches all card data (`cards.json`) in memory with O(1) lookups and prefix tables.
- **`event_data.py`**: Singleton (`event_data`) that manages JP/EN event data (`events.json`), active/past events, and banner schedules.
- **`song_data.py`**: Singleton (`song_data`) managing music tracks (`musics.json`) and chart master difficulties (`musicDifficulties.json`).
- **`music_quiz_db.py`**: Database class (`MusicQuizDB`) for `song.xlsx` used in the music guessing minigame.
- **Depended on by**: Almost all game and info cogs (e.g., `birthday.py`, `guess.py`, `profile.py`, `card.py`, `events.py`, `songs.py`).

### `utils/core/` (System Core)
- **`database.py`**: Handles all asynchronous interactions with `ichika.db` (user settings, gacha history, and server configurations).
- **`autoupdater.py`**: Validates, fetches, and syncs new assets/data from upstream Sekai-World repositories with atomic writes.
- **`romaji.py`**: Normalization and romaji conversion logic for search features.

### `utils/media/` (Media Processing)
- **`image_helper.py`**: Asynchronous image caching and fetching.
- **`audio_fx.py`**: Audio manipulation logic (FFmpeg/Pydub).

### Domain-Specific Helpers
- **`utils/game/`**: Card filtering, random sampling, and trained/untrained art validation (`cards.py`).
- **`utils/social/`**: Date calculations and Embed generation for social features (`birthday_helpers.py`, `birthday_ui.py`).
- **`utils/info/`**: Shared Embed generation and Pagination Views (`songs_ui.py`, `events_ui.py`).
- **`utils/voice/`**: Streaming player models (`GuildPlayer`), YouTube downloader logic (`yt-dlp`), and UI (`NowPlayingView`).
- **`utils/mercari_scraper/`**: High-performance, low-RAM Mercari Japan scraper library supporting both individual C2C listings (`c2c_client.py`) and Mercari Shops products (`shops_client.py`).

---

## 🧩 Features & Modules (`cogs/`)

Cogs are organized into subdirectories by category. The bot recursively loads all `.py` files in this tree.

| Module Area | Feature Description | Key Dependencies |
|:---|:---|:---|
| **`cogs/voice/`** | Music streaming (`streaming.py`) & Music Guessing minigame (`music_guess.py`). | `utils.voice.*`, `utils.media.audio_fx`, `utils.data.music_quiz_db` |
| **`cogs/game/`** | Character Guessing game (`guess.py`) & Gacha simulator (`gacha.py`). | `utils.data.*`, `utils.game.*`, `utils.core.database` |
| **`cogs/info/`** | Database lookups (Cards, Profiles, Songs, Events). | `utils.info.*`, `utils.data.*`, `utils.core.romaji` |
| **`cogs/social/`** | Server engagement (Character Birthdays, Scheduled Card of the Day). | `utils.social.*`, `utils.data.*`, `utils.core.database` |
| **`cogs/system/`** | Bot administration (Auto-updater for assets, Interactive Help). | `utils.core.autoupdater` |
| **`cogs/misc/`** | Utilities: Mercari JP search (`mercari.py`) & Vietnam fuel prices (`gas_price.py`). | `utils.mercari_scraper.*`, `aiohttp` |

---

## 🔄 Data Flow Example: Updating Game Assets

1. `cogs/system/data_updater.py` runs its scheduled task.
2. It calls `utils/core/autoupdater.py` to fetch new assets from Sekai-World repositories.
3. If new data is pulled, the system reloads the relevant singletons (`card_data`, `event_data`, `song_data`).
4. Registered cogs implementing `load_data()` are notified to refresh their in-memory views without requiring a bot restart.

---

## 🛠️ Contribution Guidelines

1. **Memory**: Use singletons from `utils.data` instead of manually loading JSONs.
2. **Separation of Concerns**: Keep Cogs small. Move Embed generation, Pagination UI, and complex calculations to the corresponding `utils/` subdirectory.
3. **Persistence**: Use `utils.core.database.py` schema for new user data.
4. **Async Execution**: Heavy tasks (Pillow/Pydub) must use `await bot.loop.run_in_executor()`.
5. **Path Consistency**: Use `BASE_DIR` from `config.py` for all file path operations to ensure compatibility across Docker/container environments.
