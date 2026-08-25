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

To host IchikaBot yourself, you'll need **Python 3.11+** and **FFmpeg** installed on your system.

### 1. Clone the Repository
```bash
git clone https://github.com/kei-kochiya/IchikaBot.git
cd IchikaBot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```
*(Ensure `FFmpeg` is installed and added to your system PATH for the music streaming module to function).*

### 3. Configuration
Create a `.env` file in the root directory and add your Discord bot token:
```env
DISCORD_TOKEN=your_bot_token_here
```

### 4. Run the Bot
```bash
python bot.py
```
*Note: Game data files and the SQLite database (`ichika.db`) will automatically download and initialize upon the first successful run.*

---

## 🛠️ Architecture & Contribution

IchikaBot uses a modular Cog architecture. We heavily utilize the Singleton pattern for massive JSON payloads and an async SQLite layer for persistence to keep RAM usage extremely low.

For developers looking to contribute, please read the **[Architecture & Contribution Guide (ARCHITECT.md)](./ARCHITECT.md)** for a deep dive into the bot's internal data flow, state management, and file dependencies.

---

<div align="center">
  <i>Developed with ❤️ for the Project Sekai community.</i>
</div>
