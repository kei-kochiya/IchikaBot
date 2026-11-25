# IchikaBot

[![Tiếng Việt](https://img.shields.io/badge/Docs-Tiếng_Việt-green)](../../README.md) [![Architecture (EN)](https://img.shields.io/badge/Architecture-English-blue)](ARCHITECT.md) [![Kiến trúc (VI)](https://img.shields.io/badge/Kiến_trúc-Tiếng_Việt-lightgrey)](../vi/ARCHITECT.md)

A Discord bot for *Project Sekai: Colorful Stage!* It looks up cards, songs, events and character profiles, simulates the gacha, runs two guessing games, posts character birthdays and a card of the day on a schedule, and links EN/JP Project Sekai accounts to render Best 30 (B30) rating charts. The bot replies in Vietnamese.

[Invite IchikaBot to a server](https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands)

## Features

- **Lookups.** Cards (with a toggle between normal and trained art), character profiles, songs (credits, release date, level and note count for every difficulty) and events (current, past, search). Game data comes from the Sekai-World master database and refreshes on its own.
- **Gacha simulator.** One or ten pulls at 6% for 4★, 15% for 3★ and 79% for 2★. The tenth card of a ten-pull is always 3★ or better, and 50 pulls without a 4★ guarantee one. Pity is saved per user. Results are drawn like the in-game result screen.
- **Character guess.** Name the character from part of a card, at three difficulties. Easy crops onto the card's own character (found with the game's close-up of them), normal crops anywhere on the card, and hard shows the card black-and-white, pixelated, blurred or inverted. Each player picks their default with `/guessmode`; it is easy until they do.
- **Music quiz.** The bot joins your voice channel and plays a 20-second clip. Commissioned songs by default, or every song; hard mode plays the clip faster, slower or reversed.
- **Announcements.** A post at midnight JST on each character's birthday (and a countdown card on other days), and a card of the day every 0.5 to 24 hours. Both are set up per server.
- **PJSK Account & B30.** Link EN or JP Project Sekai accounts via in-game Bio verification (`/pjsk link`), sync FC/AP clears automatically via Transfer ID in DMs with a fresh Transfer ID returned immediately (`/pjsk sync`, plus crash recovery via `/pjsk recover` and `suite.json` import via `/pjsk import`), and render a Best 30 rating image (`/b30` / `/pjsk b30`) using the `pjskb30` chart constant table.
- **Utilities.** Mercari Japan item lookup by link or ID with an estimated price in VND, and today's PVOIL fuel prices in Vietnam.

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
| `/pjsk link [region]` | | Link your EN/JP PJSK account via Bio |
| `/pjsk unlink [region]` | | Unlink your account and delete saved clears |
| `/pjsk profile [region] [user]` | | Show a linked PJSK profile |
| `/pjsk sync [region]` | | Sync FC/AP clears via Transfer ID (in DM) and get a new Transfer ID back |
| `/pjsk recover [region]` | | Re-issue a Transfer ID if a sync was interrupted |
| `/pjsk import [region] <file>` | | Import clears from a `suite.json` file |
| `/b30 [region] [user]` | | Render your Best 30 (B30) rating chart |
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
| `PJSK_EN_INHERIT_TOKEN` | No | JWT secret for EN `x-inherit-id-verify-token` (required for EN `/pjsk sync`) |
| `PJSK_JP_INHERIT_TOKEN` | No | JWT secret for JP `x-inherit-id-verify-token` (required for JP `/pjsk sync`) |

> [!IMPORTANT]
> **Note on JWT Tokens (`PJSK_EN_INHERIT_TOKEN` / `PJSK_JP_INHERIT_TOKEN`):**
> These JWT signing secrets are **not included** in this repository — if you want to enable live `/pjsk sync` on your own instance, **you must obtain/source them yourself** and place them in your local `.env` file (never commit `.env`).
>
> Without these tokens, all other bot features continue to work normally, and users can still generate `/b30` charts by uploading a `suite.json` file via `/pjsk import`.

### Data and files

| Path | Contents | Where it comes from |
|---|---|---|
| `gameData/static/` | Character data, nicknames, and the music quiz song list (`song.xlsx`) | The repository; update with `git pull` |
| `gameData/JP_data/`, `gameData/EN_data/` | Cards, songs and events | Downloaded on the first start, about 70 MB, then checked every 6 hours |
| `music/` | Audio for the music quiz, one file per song named by its ID (`54.mp3`) | Not in the repository: add your own |
| `ichika.db` | Gacha pity, per-server settings, and linked PJSK/B30 data | Created on the first start |
| `.gachacache/` | Downloaded card art, song jackets and B30 chart constants | Rebuilt as needed; safe to delete |

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

The default test suite runs completely offline. Live contract checks against external APIs are marked `@pytest.mark.live` and can be run with `pytest -m live`. CI runs the tests on Python 3.11 to 3.13, the linter and `pip-audit`.

## Documentation

- **English:** [Architecture & Contribution Guide (`docs/en/ARCHITECT.md`)](ARCHITECT.md)
- **Tiếng Việt:** [README tiếng Việt (`README.md`)](../../README.md) · [Kiến trúc & Hướng dẫn đóng góp (`docs/vi/ARCHITECT.md`)](../vi/ARCHITECT.md)
