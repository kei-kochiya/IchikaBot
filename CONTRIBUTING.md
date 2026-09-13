# Contributing to IchikaBot

Thank you for your interest in contributing to **IchikaBot**! This document provides guidelines and setup instructions for developers and contributors.

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.11+**
- **Git**
- **FFmpeg** (installed and added to system `PATH` for voice streaming features)

### 1. Fork & Clone
```bash
git clone https://github.com/kei-kochiya/IchikaBot.git
cd IchikaBot
```

### 2. Set Up Virtual Environment
```bash
# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell):
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
# Install runtime and development dependencies:
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 4. Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
Fill in your test bot token (`DISCORD_TOKEN`) in `.env`.

---

## 🧪 Testing & Code Quality

IchikaBot uses **Pytest** for testing and **Ruff** for linting and formatting.

### Run Tests
```bash
# Run all unit and integration tests
pytest

# Run tests with code coverage report
pytest --cov=utils --cov=cogs tests/
```

### Run Linter & Formatter
```bash
# Check code for lint errors
ruff check .

# Automatically fix lint issues where possible
ruff check . --fix

# Verify code formatting
ruff format --check .

# Format all code
ruff format .
```

---

## 🏗️ Architecture & Conventions

Please review **[ARCHITECT.md](./ARCHITECT.md)** for an overview of the bot's singleton patterns, async SQLite database, and cog directory structure.

### Key Rules:
1. **Never commit `.env` or real bot tokens.**
2. **Use Data Singletons:** Access game data via `utils.data.*` singletons (`game_data`, `card_data`, etc.) rather than manually loading JSON files.
3. **Async File I/O:** Use `aiofiles` or `aiohttp` for async network and disk access. Heavy CPU/image tasks should run in executors: `await bot.loop.run_in_executor()`.
4. **All new features must include unit tests in `tests/`.**

---

## 🌿 Git & Pull Request Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```
2. Commit your changes using conventional commit messages (`feat: ...`, `fix: ...`, `docs: ...`, `test: ...`).
3. Ensure all tests and lint checks pass before pushing:
   ```bash
   ruff check .
   pytest
   ```
4. Push your branch and open a Pull Request against `main`.
