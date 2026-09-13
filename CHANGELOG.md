# Changelog

All notable changes to **IchikaBot** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-09-13

### Added
- **Automated Test Suite**: Full `pytest` testing suite with coverage for data singletons, database queries, romaji matching, minigame logic, gacha rates, and cog loading.
- **System Health Diagnostics (`cogs/system/health.py`)**: `/health` slash command and `!health` / `!ping` prefix command tracking WebSocket latency, bot uptime, RAM usage, SQLite latency, and background loop status.
- **Code Quality & Linting**: `pyproject.toml` configuration for `ruff` and `pytest`.
- **Security & Secret Hygiene**: Committed `.env.example` and updated `.gitignore` rules.
- **Docker Containerization**: Added production `Dockerfile` with system FFmpeg and `docker-compose.yml` with persistent volume management.
- **CI/CD Workflows**: GitHub Actions workflow (`.github/workflows/ci.yml`) for automated linting, test execution, and dependency auditing.
- **Dependabot Integration**: Automated weekly dependency security scanning.
- **Developer Documentation**: Added `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, and issue/PR templates.

### Changed
- **Dependency Management**: Pinned runtime dependencies in `requirements.txt` and separated dev dependencies into `requirements-dev.txt`.
- **Robustness**: Added `@task.error` handlers to background task loops in `birthday.py`, `card_of_day.py`, and `data_updater.py` with automatic traceback logging and recovery.
- **Romaji Search**: Added extended combinations (`je`, `she`, `che`) for enhanced Japanese search accuracy.
