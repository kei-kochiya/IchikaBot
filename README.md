# IchikaBot

A Discord bot for *Project Sekai: Colorful Stage!* It looks up cards, songs, events and character profiles, simulates the gacha, runs two guessing games, and posts character birthdays and a card of the day on a schedule. The bot replies in Vietnamese.

[Invite IchikaBot to a server](https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands)

## Features

- **Lookups.** Cards (with a toggle between normal and trained art), character profiles, songs (credits, release date, level and note count for every difficulty) and events (current, past, search). Game data comes from the Sekai-World master database and refreshes on its own.
- **Gacha simulator.** One or ten pulls at 6% for 4★, 15% for 3★ and 79% for 2★. The tenth card of a ten-pull is always 3★ or better, and 50 pulls without a 4★ guarantee one. Pity is saved per user. Results are drawn like the in-game result screen.
- **Character guess.** Name the character from part of a card, at three difficulties. Easy crops onto the card's own character (found with the game's close-up of them), normal crops anywhere on the card, and hard shows the card black-and-white, pixelated, blurred or inverted. Each player picks their default with `/guessmode`; it is easy until they do.
- **Music quiz.** The bot joins your voice channel and plays a 20-second clip. Commissioned songs by default, or every song; hard mode plays the clip faster, slower or reversed.
- **Announcements.** A post at midnight JST on each character's birthday (and a countdown card on other days), and a card of the day every 0.5 to 24 hours. Both are set up per server.
- **Utilities.** Mercari Japan item lookup and search with an estimated price in VND, and today's PVOIL fuel prices in Vietnam.

## Commands

Slash commands are the main way in. Most also have a prefix form: type `!` (or `-`) instead of `/`. The music quiz and the server settings only work inside a server. `/help` lists everything in Discord, and `/help <category>` shows one category in detail.

| Command | Prefix | What it does |
|---|---|---|
| `/card <name>` | | Look up a card by name or ID |
| `/gacha pull [amount]` | | Pull 1 or 10 cards |
| `/gacha pity` | | Show your pity count |
| `/song search <query>` | `!song <query>` | Search songs |
| `/song info <name>` | | One song in detail |
| `/song random` | `!songr` | A random song |
| `/profile info <name>` | `!profile <name>` | A character's profile |
| `/event current` | `!event` | The running or next event |
| `/event history` | `!events` | Past events |
| `/event search <name>` | `!eventsearch <name>` | Search events |
| `/birthday check` | `!bday` | Today's and upcoming birthdays |
| `/birthday countdown [name]` | `!bdayu [name]` | Days until a birthday, with a card |
| `/guess [mode]` | | Start a character guess (easy, normal or hard) |
| `/guessmode [mode]` | | Set your default difficulty, or show it |
| `/songguess [mode] [pool]` | `!sg`, `!sgv`, `!sga`, `!sgav` | Start a music quiz (`v`: with effects, `a`: all songs) |
| `/mercari <link or ID>` | `!mercari`, `!mer` | Look up a Mercari item |
| `/mercarisearch <keyword>` | `!msearch` | Search Mercari |
| `/gasprice` | `!gasprice` | Today's fuel prices |

In both games, answer with `-g <answer>` in the channel where the round started.

Server settings need the **Manage Server** permission: `/birthday channel`, `/birthday disable`, `/cotd channel`, `/cotd interval`, `/cotd now` and `/cotd disable` (`/cotd status` is open to everyone). `/update_data`, which checks for new game data immediately, needs **Administrator**.

## Permissions

The invite link asks for Send Messages, Embed Links, Attach Files, Add Reactions and Read Message History; Connect and Speak for the music quiz; and Use Application Commands for slash commands.

## Hosting the bot yourself

### Requirements

- Python 3.11 or newer.
- FFmpeg on the `PATH`, for the music quiz. On Linux, also `libopus`.
- A Discord application with a bot token. In the Developer Portal, turn on the **Message Content** intent: prefix commands and `-g` answers read message text.

### Install and run

```bash
git clone https://github.com/kei-kochiya/IchikaBot.git
cd IchikaBot
pip install -r requirements.txt
cp .env.example .env
```

Put your bot token in `.env`, then start the bot:

```bash
python bot.py
```

Slash commands are registered each time the bot starts. The bot owner can register them again with `!sync`.

### Settings (`.env`)

| Variable | Required | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | Yes | The bot's token |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING` or `ERROR` |

### Data and files

| Path | Contents | Where it comes from |
|---|---|---|
| `gameData/static/` | Character data, nicknames, and the music quiz song list (`song.xlsx`) | The repository; update with `git pull` |
| `gameData/JP_data/`, `gameData/EN_data/` | Cards, songs and events | Downloaded on the first start, about 70 MB, then checked every 6 hours |
| `music/` | Audio for the music quiz, one file per song named by its ID (`54.mp3`) | Not in the repository: add your own |
| `ichika.db` | Gacha pity and each server's settings | Created on the first start |
| `.gachacache/` | Downloaded card art and images | Rebuilt as needed; safe to delete |

Until the first download of `JP_data` and `EN_data` finishes, card, song and event commands have no data. That usually takes about a minute.

### Moving to another host

Stop the bot, then copy `.env`, `music/` and `ichika.db` to the new machine. Copying `gameData/JP_data`, `gameData/EN_data` and `gameData/updaterState.json` as well skips the first download.

## Development

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
ruff format --check .
```

The test suite runs offline, except `tests/test_mercari/test_scraper.py` and `tests/test_mercari/test_memory.py`, which call the live Mercari API. CI runs the tests on Python 3.11 to 3.13, the linter and `pip-audit`.

[ARCHITECT.md](./ARCHITECT.md) explains how the code is organised: the cogs, the shared data loaders, the database and the data updater.
