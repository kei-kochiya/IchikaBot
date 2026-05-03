# IchikaBot

Discord bot for Project Sekai: Colorful Stage.

## Features

- Character profiles and card lookup
- Birthday announcements with countdown
- Gacha simulation with pity system
- Song database and guessing game
- Event tracker
- YouTube music streaming with queue management
- Card of the Day announcements

## Recent Updates

### SQLite Migration
User data (gacha pity, guild settings) is now stored in `ichika.db` instead of flat JSON files.
Existing data from `pityData.json`, `birthdaySettings.json`, and `cardOfDaySettings.json` is migrated automatically on first run.

### Streaming Now-Playing Embed
`/stream play` now posts a single persistent embed that updates in place as tracks change.
The embed includes interactive buttons directly in the message:

| Button | Action |
|--------|--------|
| ⏸ / ▶ | Pause / Resume |
| ⏭ | Skip current track |
| 🔁 | Cycle loop mode (Off → Track → Queue) |
| 🔀 | Shuffle the queue |
| ⏹ | Stop and leave voice channel |

> Only users currently in the same voice channel as the bot can use the buttons.

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create `.env` file with your Discord bot token:
   ```
   DISCORD_TOKEN=your_discord_bot_token
   ```
4. Run the bot:
   ```
   python bot.py
   ```

Game data files are auto-downloaded on first run. The SQLite database (`ichika.db`) is created automatically.

## File Structure

```
bot.py              # Main entry point
config.py           # Configuration and constants
cogs/               # Command modules
  birthday.py       # Birthday announcements
  card.py           # Card lookup
  card_of_day.py    # Scheduled card posts
  events.py         # Event tracker
  gacha.py          # Gacha simulation
  guess.py          # Card guessing game
  help.py           # Help command
  mercari.py        # Mercari search
  music.py          # Song guessing game
  profile.py        # Character profiles
  songs.py          # Song database
  stamps.py         # Stamp lookup
  streaming.py      # YouTube music player
  tournament.py     # Tournament tools
  data_updater.py   # Auto-update game data
utils/              # Shared utilities
  cards.py          # Card image helpers
  card_data.py      # Card data singleton
  database.py       # Async SQLite layer (aiosqlite)
  game_data.py      # Character data helpers
  autoupdater.py    # Data fetching
  romaji.py         # Romaji search helpers
gameData/           # Game data files (auto-downloaded)
ichika.db           # SQLite database (auto-created)
```

## Requirements

- Python 3.11+
- discord.py
- aiohttp, aiofiles, aiosqlite
- Pillow, pydub
- yt-dlp, FFmpeg (must be in PATH for music streaming)
