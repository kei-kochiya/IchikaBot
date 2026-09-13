# IchikaBot Repository Quality, Robustness & CI/CD Design

**Date**: 2026-09-13
**Author**: Antigravity & User
**Status**: Approved

---

## 1. Executive Summary

This document establishes the architecture, tooling, quality controls, and automation pipeline for IchikaBot, a 24/7 Discord bot dedicated to Project Sekai: Colorful Stage!. The improvements address all findings from the repository audit:
- Lack of automated tests
- Silent exception swallowing and missing runtime health checks
- Unpinned dependencies and missing lockfiles/security auditing
- Missing linters/formatters
- Incomplete onboarding documents (.env.example, CONTRIBUTING.md, CHANGELOG.md, Dockerfile)
- Lack of CI/CD pipeline and GitHub repository automations

---

## 2. Architecture & Robustness

### 2.1 Error Handling & Task Hardening
1. **Background Task Loops**:
   - Background tasks in `cogs/social/birthday.py`, `cogs/social/card_of_day.py`, and `cogs/system/data_updater.py` must define `@task_name.error` handlers.
   - When a transient error occurs (e.g. Discord rate limit, temporary network timeout), the handler logs the error with full stack trace (`logger.exception`) and schedules task recovery.
2. **Specific Exception Catches**:
   - Replace generic `except Exception:` blocks with specific exceptions (`discord.Forbidden`, `discord.NotFound`, `json.JSONDecodeError`, `FileNotFoundError`) wherever expected failure modes exist.
   - Avoid silent `pass` in `except` blocks; always record diagnostic logs.

### 2.2 Health & Diagnostics Cog (`cogs/system/health.py`)
Provides both slash (`/health`) and prefix (`!health`, `!ping`) commands returning:
- **WebSocket Latency**: Bot gateway ping in milliseconds.
- **Bot Uptime**: Time elapsed since startup.
- **System Metrics**: Process RAM usage (MB) and Python/discord.py versions.
- **Database Status**: Active SQLite connection ping time.
- **Task Loop Health**: Current running state for `BirthdayCog.birthday_check_task`, `CardOfDayCog.card_loop`, and `DataUpdaterCog.scheduled_update`.
- **Loaded Extensions**: Verification of all 15+ cogs loaded and active.

---

## 3. Automated Test Suite (Pytest)

### 3.1 Test Directory Structure
```
tests/
├── __init__.py
├── conftest.py                  # Pytest fixtures: mock Bot, in-memory test DB, fixture paths
├── test_core/
│   ├── test_database.py        # SQLite async DB creation, pity counts, birthday subscriptions
│   ├── test_romaji.py          # Romaji normalization, accent removal, fuzzy search matching
│   └── test_autoupdater.py     # Source registration and hash/etag check logic
├── test_data/
│   ├── test_singletons.py      # game_data, card_data, event_data, song_data, stamp_data integrity
│   └── test_music_quiz_db.py   # Song Excel parsing, answer normalization, guess matching
├── test_game/
│   ├── test_gacha_logic.py     # 2★/3★/4★ probability weights, pity counter increments & resets
│   └── test_tournament.py      # Bracket progression, round generation, point calculations
├── test_cogs/
│   └── test_cog_loading.py     # Loads all cogs into a mock commands.Bot to prevent startup regressions
└── test_social/
    └── test_birthday_helpers.py# Birthday lookup, leap year handling, and embed date formatting
```

### 3.2 Fixtures (`conftest.py`)
- `mock_bot`: An initialized `commands.Bot(command_prefix="!", intents=..., help_command=None)`.
- `temp_db`: Temporary SQLite database initialized using `database.init_db()` for isolated testing.
- `sample_game_data`: Valid test data fixtures for card and song assertions.

---

## 4. Tooling, Dependencies & Formatting

### 4.1 Dependency Management
- **`requirements.txt`**: Pin runtime dependencies to tested version ranges (`discord.py>=2.4.0,<2.8.0`, `aiohttp>=3.10.0,<4.0.0`, `aiosqlite>=0.20.0,<1.0.0`, `Pillow>=10.4.0,<13.0.0`, `pydub>=0.25.1,<1.0.0`, `PyNaCl>=1.5.0,<2.0.0`, `davey>=0.1.6,<1.0.0`, `mercapi>=0.4.2,<1.0.0`, `yt-dlp>=2024.8.0`, `openpyxl>=3.1.0,<4.0.0`, `python-dotenv>=1.0.0,<2.0.0`).
- **`requirements-dev.txt`**: Development packages (`pytest>=8.3.0`, `pytest-asyncio>=0.24.0`, `pytest-cov>=5.0.0`, `ruff>=0.6.0`, `pip-audit>=2.7.0`).

### 4.2 Configuration (`pyproject.toml`)
- **Ruff**: Python 3.11 target, line length 100, lint rule selection (`E`, `F`, `W`, `I`, `B`, `UP`, `SIM`).
- **Pytest**: `asyncio_mode = "auto"`, `testpaths = ["tests"]`.

---

## 5. Documentation & Containerization

### 5.1 Documentation
- **`.env.example`**: Committed template with `DISCORD_TOKEN` and optional debug variables.
- **`CONTRIBUTING.md`**: Setup guide, running tests, linting, code style conventions, and PR flow.
- **`CHANGELOG.md`**: Initialized changelog following Keep a Changelog / SemVer.
- **`SECURITY.md`**: Vulnerability reporting and Discord token security hygiene.
- **`.gitignore`**: Whitelist documentation (`!CONTRIBUTING.md`, `!CHANGELOG.md`, `!SECURITY.md`, `!docs/**/*.md`) and ignore test/lint caches.

### 5.2 Containerization
- **`Dockerfile`**: Debian `python:3.11-slim` base with system `ffmpeg` and audio libraries, unprivileged user, and clean workdir.
- **`docker-compose.yml`**: Production compose definition mounting `ichika.db`, `logs/`, and `gameData/` with `restart: unless-stopped` and container healthcheck.

---

## 6. GitHub CI/CD & Maintenance

### 6.1 GitHub Actions Workflow (`.github/workflows/ci.yml`)
Runs on push and pull requests targeting `main`:
1. **Lint**: `ruff check .` and `ruff format --check .`
2. **Test**: `pytest --cov=utils --cov=cogs tests/`
3. **Security Audit**: `pip-audit` to detect vulnerable packages.

### 6.2 GitHub Automations
- **`.github/dependabot.yml`**: Weekly vulnerability scanning for pip dependencies and GitHub Actions.
- **`.github/ISSUE_TEMPLATE/`**: Bug report and feature request templates.
- **`.github/pull_request_template.md`**: PR review checklist.
- **Release Guide**: Documentation for creating git tags and GitHub releases.
