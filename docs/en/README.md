<div align="center">

# IchikaBot

**A Vietnamese-language Discord bot for *Project Sekai: Colorful Stage!***<br/>
Game Lookups · Gacha Simulator · 4 Guessing Minigames · PJSK Account Sync &amp; Best 30

[![Invite to Discord](https://img.shields.io/badge/Discord-Invite_IchikaBot-33AAEE?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands)
[![CI](https://img.shields.io/github/actions/workflow/status/kei-kochiya/IchikaBot/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/kei-kochiya/IchikaBot/actions)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-4455DD?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

[Features](#features) · [Commands](#commands) · [Self-hosting](#self-hosting) · [Architecture](ARCHITECT.md) · [Tiếng Việt](../../README.md)

</div>

---

## Features

| Area | Details |
|---|---|
| **Lookups** | Cards (untrained / trained), character profiles, songs (difficulty, note count, credits), and events from Sekai-World. |
| **Gacha Simulator** | 1-pull or 10-pull (`6%` 4★ · `15%` 3★ · `79%` 2★; 10th slot ≥ 3★; 4★ pity at 50). |
| **4 Guessing Minigames** | Type <kbd>-g &lt;answer&gt;</kbd> to guess characters from cards (`/guess`), songs from jacket art (`/jacketguess`), songs from **Master / Append** chart slices (`/chartguess`), or 20s voice clips (`/songguess`). |
| **PJSK Account & B30** | Link EN/JP via Bio (`/pjsk link`), sync FC/AP clears via Transfer ID (`/pjsk sync`, recover with `/pjsk recover`), and render Best 30 images using `pjskb30` (`/b30`). |
| **Automation & Utilities** | Midnight `JST` character birthday posts, scheduled Card of the Day (`0.5–24h`), Mercari Japan lookup (VND estimate), and Vietnam PVOIL fuel prices. |

---

## Commands

IchikaBot uses **Slash Commands (`/`)**. Run `/help` or `/help <category>` in Discord to browse commands.

<details open>
<summary><strong>Lookups &amp; Gacha</strong></summary>

| Command | Description |
|---|---|
| `/card <name>` | Look up a card by name or ID (with untrained / trained toggle) |
| `/profile info <name>` | View a character's detailed profile |
| `/song search <query>` | Search songs (JP / EN / Romaji) |
| `/song info <name>` | View song credits, difficulty levels and note counts |
| `/song random` | Pick a random song (supports level filters) |
| `/event current` | Current or upcoming event |
| `/event history` | Past events |
| `/event search <name>` | Search events by name |
| `/gacha pull [amount]` | Pull 1 or 10 cards |
| `/gacha pity` | Check your current pity counter |

</details>

<details open>
<summary><strong>Minigames</strong></summary>

| Command | Description |
|---|---|
| `/guess [mode]` | Guess the character from card art (`easy` / `normal` / `hard`) |
| `/guessmode [mode]` | View or set your default difficulty for `/guess` |
| `/jacketguess [mode]` | Guess the song from cropped / effected jacket art |
| `/chartguess [difficulty] [mode]` | Guess the song from a `master` or `append` chart slice |
| `/songguess [mode] [pool]` | 20s voice audio quiz (Commissioned or All songs; optional audio effects) |

</details>

<details>
<summary><strong>Account &amp; Best 30</strong></summary>

| Command | Description |
|---|---|
| `/pjsk link [region]` | Link an EN/JP account via Bio verification |
| `/pjsk profile [region] [user]` | View a linked PJSK profile |
| `/pjsk sync [region]` | Sync FC/AP clears via Transfer ID in DM and receive a new Transfer ID |
| `/pjsk recover [region]` | Re-issue a Transfer ID if a sync was interrupted |
| `/pjsk unlink [region]` | Unlink account and delete saved clears |
| `/b30 [region] [user]` | Render a Best 30 rating image (alias: `/pjsk b30`) |

</details>

<details>
<summary><strong>Birthdays, Automation &amp; Utilities</strong></summary>

| Command | Description |
|---|---|
| `/birthday check` | Today's and upcoming birthdays |
| `/birthday countdown [name]` | Countdown to a birthday with card art |
| `/cotd status` | Check server Card of the Day settings |
| `/mercari <link or ID>` | Look up a Mercari Japan listing with VND estimate |
| `/gasprice` | Today's PVOIL fuel prices |

> **Server admin commands:** `/birthday channel`, `/birthday disable`, `/cotd channel`, `/cotd interval`, `/cotd now`, and `/cotd disable` require **Manage Server**. `/update_data` requires **Administrator**.

</details>

---

## Self-hosting

### 1. Requirements

- **Python 3.11+**
- **FFmpeg** on `PATH` (for `/songguess`; on Linux also install `libopus`)
- **Discord Bot Token** with **Message Content Intent** enabled in the Developer Portal (required for `-g` minigame answers). Required permissions: `Send Messages`, `Embed Links`, `Attach Files`, `Add Reactions`, `Read Message History`, `Use Application Commands`, plus `Connect` & `Speak` for voice.

### 2. Install and run

```bash
git clone https://github.com/kei-kochiya/IchikaBot.git
cd IchikaBot
pip install -r requirements.txt
cp .env.example .env
# Add DISCORD_TOKEN to .env
python bot.py
```

Slash commands sync automatically on startup (the bot owner can force a re-sync via `@IchikaBot sync`). First startup takes about a minute to download game data (~70 MB).

### 3. Environment variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Discord bot token |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |
| `PJSK_EN_INHERIT_TOKEN` | No | JWT secret for EN `x-inherit-id-verify-token` (`/pjsk sync`) |
| `PJSK_JP_INHERIT_TOKEN` | No | JWT secret for JP `x-inherit-id-verify-token` (`/pjsk sync`) |

> [!IMPORTANT]
> The JWT signing secrets (`PJSK_EN_INHERIT_TOKEN`, `PJSK_JP_INHERIT_TOKEN`) are **not included** in this repository. To enable `/pjsk sync` on a self-hosted instance, you must **source and configure them yourself** in `.env`. Without them, all other features, including `/pjsk link` and `/pjsk profile`, work normally.

<details>
<summary><strong>Local data paths &amp; host migration</strong></summary>

| Path | Contents | Source |
|---|---|---|
| `gameData/static/` | Characters, nicknames, `song.xlsx` | Included in repo (`git pull` to update) |
| `gameData/JP_data/`, `EN_data/` | Cards, songs, events | Downloaded on first start, checked every 6 hours |
| `music/` | Audio files for `/songguess`, named by song ID (`54.mp3`) | Not in repo — add your own |
| `ichika.db` | SQLite store for pity, server settings, PJSK/B30 data | Created on first start |
| `.assetcache/` | Cached card art, jackets, charts and B30 constants | Rebuilt as needed; safe to delete |

**Migrating hosts:** stop the bot and copy `.env`, `music/`, and `ichika.db` (also copy `gameData/JP_data`, `gameData/EN_data`, and `gameData/updaterState.json` to skip the initial download).

</details>

---

## Development

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
ruff format --check .
```

The default test suite runs completely offline (`pytest -m live` runs live API contract checks). CI runs `pytest` on Python 3.11–3.13 along with `ruff` and `pip-audit`.

---

<div align="center">

<sub>✦ · · · ── ☆ ── · · · ✦</sub><br/>
<sub>Made with ♥ for the <strong>Project Sekai Vietnamese community</strong></sub>

</div>
