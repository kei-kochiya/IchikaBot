# IchikaBot Architecture & Contribution Guide

Welcome to the IchikaBot source code! This document provides an overview of the bot's internal architecture, file structure, and module dependencies. It is intended for developers who wish to understand or contribute to the project.

## 🏗️ Architecture Overview

IchikaBot is built using `discord.py` and follows a modular **Cog-based architecture**. Each major feature is encapsulated in its own class (a "Cog") within organized subdirectories under `cogs/`.

To ensure performance and low RAM usage, the bot heavily utilizes the **Singleton pattern** for loading large game data files. Persistent data is stored via an async SQLite database.

---

## 📂 Core Components & Utilities (`utils/`)

The `utils/` directory acts as the backbone of the bot. Cogs should rely on these utilities rather than loading raw JSON/data themselves.

### `utils/card_data.py` (CardDataManager)
- **Role**: Singleton that parses and holds all card data (`cards.json`) in memory once.
- **Depended on by**: `cogs/info/card.py`, `cogs/game/gacha.py`, `cogs/game/guess.py`, `cogs/social/birthday.py`, `cogs/info/profile.py`, `cogs/social/card_of_day.py`, `cogs/game/tournament.py`, `cogs/system/data_updater.py`.

### `utils/game_data.py` (GameDataManager)
- **Role**: Singleton that manages character and nickname data.
- **Depended on by**: `cogs/game/guess.py`, `cogs/social/birthday.py`, `cogs/game/tournament.py`.

### `utils/database.py` (Async SQLite Layer)
- **Role**: Handles all database interactions (`ichika.db`) asynchronously.
- **Depended on by**: `cogs/game/gacha.py`, `cogs/voice/streaming.py`, `bot.py` (for initialization).

---

## 🧩 Features & Modules (`cogs/`)

Cogs are organized into subdirectories by category. The bot recursively loads all `.py` files in this tree.

| Module Path | Feature Description | Key Dependencies |
|:---|:---|:---|
| **`voice/`** | | |
| `streaming.py` | YouTube audio player with persistent UI. | `yt-dlp`, `utils.database` |
| `music.py` | Audio guessing minigame (song.xlsx). | `pydub`, FFmpeg |
| **`game/`** | | |
| `tournament.py` | 5-round progressive card tournament. | `utils.card_data` |
| `guess.py` | Single-round card guessing game. | `utils.card_data` |
| `gacha.py` | Gacha simulator with pity system. | `utils.database` |
| **`info/`** | | |
| `card.py` | High-res card artwork search. | `utils.card_data` |
| `profile.py` | Character profile lookups. | `utils.card_data` |
| `songs.py` | Song database lookup. | `utils.romaji` |
| `events.py` | Event tracking. | Static JSONs |
| `stamps.py` | Stamp search. | Static JSONs |
| **`social/`** | | |
| `birthday.py` | Birthday announcements. | `utils.game_data` |
| `card_of_day.py` | Daily scheduled card posts. | `utils.card_data` |
| **`system/`** | | |
| `data_updater.py`| Scheduled game data refresh. | `utils.autoupdater` |
| `help.py` | Help command. | - |
| **`misc/`** | | |
| `mercari.py` | Mercari JP lookup. | External API |

---

## 🔄 Data Flow Example: Updating Game Assets

1. `cogs/system/data_updater.py` runs its scheduled task.
2. It calls `utils/autoupdater.py` to fetch new assets.
3. If `cards.json` changes, it calls `CardDataManager.reload()`.
4. All cogs instantly access new data without a restart.

---

## 🛠️ Contribution Guidelines

1. **Memory**: Use singletons from `utils.card_data` or `utils.game_data` instead of manual JSON loads.
2. **Persistence**: Use `utils.database.py` schema for new user data.
3. **Async**: Heavy tasks (Pillow/Pydub) must use `await bot.loop.run_in_executor()`.
4. **Organization**: Place new cogs in the appropriate subdirectory within `cogs/`.
