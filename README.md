<div align="center">
  <h1>IchikaBot</h1>
  <p><i>A feature-rich Discord bot dedicated to Project Sekai: Colorful Stage!</i></p>

  <p>
    <a href="https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands">Invite Bot</a>
    ·
    <a href="#features">Features</a>
    ·
    <a href="#setup--installation">Setup</a>
  </p>
</div>

---

<h2 id="features">✨ Features</h2>

IchikaBot brings the world of Project Sekai directly to your Discord server with a suite of interactive, automated, and entertainment modules:

### 🎮 Minigames & Entertainment
- **Card Tournament**: A multi-round guessing game with progressive visual hints (grayscale -> colour -> full art).
- **Character Guess**: Guess the character from cropped, blurred, pixelated, or inverted card images.
- **Music Quiz**: Test your knowledge with audio snippets of game songs, featuring modifiers like 1.5x speed, 0.75x slow, and reverse playback!
- **Gacha Simulator**: Pull for cards with realistic rates and an integrated pity system that saves to your profile.
- **YouTube Streaming**: High-quality music streaming with playlist support, looping, volume control, and a persistent interactive Now-Playing UI.

### 📚 Game Data & Market Lookup
- **Character Profiles & Cards**: Detailed lookups for character lore, stats, and high-resolution card artwork with normal/trained toggle.
- **Song Database**: Browse the game's discography including BPM, difficulties, notes, and duration with interactive pagination.
- **Event Tracker**: Stay updated with current, upcoming, and historical in-game events.
- **Stamps**: Search and browse in-game stamps by keyword or character.
- **Mercari Lookup**: Real-time product search and details from Mercari Japan.

### 🔔 Automated Announcements
- **Card of the Day**: Automated periodic card showcase with interactive trained/normal art toggle for your server.
- **Birthday Notifications**: Never miss a character's birthday with automated announcements, calendar schedules, and countdowns.

---

<h2 id="permissions--invite">🔑 Permissions & Invite</h2>

- **Text:** `Send Messages`, `Embed Links`, `Attach Files`, `Add Reactions`, `Read Message History`.
- **Voice:** `Connect`, `Speak` (For Music streaming).
- **Advanced:** `Use Application Commands` (To use slash command `/`).

> **Link Invite:**  
> [Invite](https://discord.com/oauth2/authorize?client_id=1416351312039383051&permissions=2150746176&integration_type=0&scope=bot%20applications.commands).

---

<h2 id="setup--installation">🚀 Setup & Installation</h2>

### Option A: Standard Setup (Python 3.11+)

1. **Clone the Repository**
   ```bash
   git clone https://github.com/kei-kochiya/IchikaBot.git
   cd IchikaBot
   ```

2. **Install Dependencies & FFmpeg**
   ```bash
   pip install -r requirements.txt
   ```
   *(Ensure `FFmpeg` is installed and in your system PATH for audio/music streaming).*

3. **Configure Environment**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and insert your Discord Bot Token.

4. **Run the Bot**
   ```bash
   python bot.py
   ```

---

### Option B: Docker Deployment (Recommended for Servers)

Run IchikaBot in a container with FFmpeg and all system dependencies pre-configured:
```bash
# 1. Create .env from template
cp .env.example .env

# 2. Start the container in background
docker compose up -d

# 3. View live logs
docker compose logs -f
```

---

## 🧪 Testing & Quality Assurance

Run the automated test suite and linter:
```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests with coverage
pytest --cov=utils --cov=cogs tests/

# Run Ruff linter & formatter check
ruff check .
ruff format --check .
```

---

## 🛠️ Architecture & Documentation

- **[Architecture Guide (ARCHITECT.md)](./ARCHITECT.md)**: Deep dive into the bot's data singletons, memory optimizations, and async SQLite layer.
- **[Contributing Guide (CONTRIBUTING.md)](./CONTRIBUTING.md)**: Guidelines for local development, tests, and opening PRs.
- **[Changelog (CHANGELOG.md)](./CHANGELOG.md)**: Version release notes and migration history.
- **[Security Policy (SECURITY.md)](./SECURITY.md)**: Vulnerability disclosure and secret handling.

---

<div align="center">
  <i>Developed with ❤️ for the Project Sekai community.</i>
</div>
