# IchikaBot

Discord bot for Project Sekai: Colorful Stage.

## Features

- Character profiles and card lookup
- Birthday announcements with countdown
- Gacha simulation with pity system
- Song database and guessing game
- Event tracker

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create `.env` file with your Discord bot token:
   ```
   TOKEN=your_discord_bot_token
   ```
4. Run the bot:
   ```
   python bot.py
   ```

Game data files are auto-downloaded on first run.

## File Structure

```
bot.py              # Main entry point
config.py           # Configuration and constants
cogs/               # Command modules
  birthday.py       # Birthday announcements
  card.py           # Card lookup
  events.py         # Event tracker
  gacha.py          # Gacha simulation
  profile.py        # Character profiles
  songs.py          # Song database
  stamps.py         # Stamp lookup
  music.py          # Song guessing game
  help.py           # Help command
  data_updater.py   # Auto-update game data
utils/              # Shared utilities
  cards.py          # Card image helpers
  game_data.py      # Character data helpers
  autoupdater.py    # Data fetching
gameData/           # Game data files (auto-downloaded)
assets/             # Local image assets
```

## Requirements

- Python 3.11+
- discord.py
- aiohttp, aiofiles
- Pillow, pydub
