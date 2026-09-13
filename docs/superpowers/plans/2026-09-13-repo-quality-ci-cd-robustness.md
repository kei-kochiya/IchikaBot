# IchikaBot Repository Quality, Robustness & CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a complete, robust engineering foundation for IchikaBot with pinned dependencies, full Pytest test coverage, code linting/formatting via Ruff, health diagnostics, Docker containerization, and GitHub Actions CI/CD.

**Architecture:** Modular test suite testing isolated singletons, core database, and mock cog injection without requiring a live Discord token. Error hardening using task loop recovery and specific exception logging. Standardized Docker + GitHub Actions workflows.

**Tech Stack:** Python 3.11+, discord.py 2.4+, pytest, pytest-asyncio, pytest-cov, ruff, pip-audit, Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-repo-quality-ci-cd-robustness-design.md`

## Global Constraints
- Do not break existing user command interfaces (`!`, `/`).
- Tests must execute locally in under 10 seconds without external network dependencies or live Discord tokens.
- Maintain documentation integrity and adherence to PEP 8 / Ruff style.

---

### Task 1: Environment & Tooling Setup

**Files:**
- Create: `.env.example`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: None
- Produces: Pinned dependencies, development environment, Ruff and Pytest configs.

- [ ] **Step 1: Create `.env.example`**
- [ ] **Step 2: Pin `requirements.txt` and create `requirements-dev.txt`**
- [ ] **Step 3: Configure `pyproject.toml` for Ruff & Pytest**
- [ ] **Step 4: Install dev requirements & verify `ruff --version` and `pytest --version`**
- [ ] **Step 5: Commit changes**

---

### Task 2: Pytest Fixtures & Core Utility Tests

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_core/__init__.py`
- Create: `tests/test_core/test_database.py`
- Create: `tests/test_core/test_romaji.py`
- Create: `tests/test_core/test_autoupdater.py`

**Interfaces:**
- Consumes: `utils/core/database.py`, `utils/core/romaji.py`, `utils/core/autoupdater.py`
- Produces: Test harness for database operations, romaji conversion, autoupdater registration.

- [ ] **Step 1: Write `tests/conftest.py` with mock bot and in-memory test database fixtures**
- [ ] **Step 2: Write tests in `test_database.py`, `test_romaji.py`, `test_autoupdater.py`**
- [ ] **Step 3: Run pytest on core tests: `pytest tests/test_core/ -v`**
- [ ] **Step 4: Verify all core tests pass**
- [ ] **Step 5: Commit changes**

---

### Task 3: Data Singletons & Minigame Logic Tests

**Files:**
- Create: `tests/test_data/__init__.py`
- Create: `tests/test_data/test_singletons.py`
- Create: `tests/test_data/test_music_quiz_db.py`
- Create: `tests/test_game/__init__.py`
- Create: `tests/test_game/test_gacha_logic.py`
- Create: `tests/test_game/test_tournament.py`
- Create: `tests/test_social/__init__.py`
- Create: `tests/test_social/test_birthday_helpers.py`

**Interfaces:**
- Consumes: `utils/data/*`, `utils/game/*`, `utils/social/*`
- Produces: Regression tests for singletons, Excel parsing, gacha probability, tournament brackets, birthday logic.

- [ ] **Step 1: Write tests for data singletons (`test_singletons.py`, `test_music_quiz_db.py`)**
- [ ] **Step 2: Write tests for game logic & birthday helpers (`test_gacha_logic.py`, `test_tournament.py`, `test_birthday_helpers.py`)**
- [ ] **Step 3: Run pytest on data, game, and social tests: `pytest tests/test_data/ tests/test_game/ tests/test_social/ -v`**
- [ ] **Step 4: Verify all tests pass**
- [ ] **Step 5: Commit changes**

---

### Task 4: Cog Loading & Integration Tests

**Files:**
- Create: `tests/test_cogs/__init__.py`
- Create: `tests/test_cogs/test_cog_loading.py`

**Interfaces:**
- Consumes: All 15+ cogs in `cogs/`
- Produces: Automated verification that every cog loads into a `commands.Bot` instance without error.

- [ ] **Step 1: Write `tests/test_cogs/test_cog_loading.py`**
- [ ] **Step 2: Run pytest: `pytest tests/test_cogs/test_cog_loading.py -v`**
- [ ] **Step 3: Verify all 15 cogs load with 0 failures**
- [ ] **Step 4: Commit changes**

---

### Task 5: Architecture Hardening & Health Monitoring Cog

**Files:**
- Create: `cogs/system/health.py`
- Modify: `cogs/social/birthday.py` (add task error handler)
- Modify: `cogs/social/card_of_day.py` (add task error handler)
- Modify: `cogs/system/data_updater.py` (add task error handler)
- Create: `tests/test_cogs/test_health_cog.py`

**Interfaces:**
- Consumes: `discord.ext.tasks`, `utils/core/database.py`, `cogs/system/health.py`
- Produces: `/health` command, task recovery listeners.

- [ ] **Step 1: Implement `cogs/system/health.py` with latency, uptime, memory, DB, and task status**
- [ ] **Step 2: Add `@task.error` handlers in `birthday.py`, `card_of_day.py`, `data_updater.py`**
- [ ] **Step 3: Write tests for HealthCog in `tests/test_cogs/test_health_cog.py`**
- [ ] **Step 4: Run pytest on health cog and cogs test suite**
- [ ] **Step 5: Commit changes**

---

### Task 6: Documentation & Docker Containerization

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `CHANGELOG.md`
- Create: `SECURITY.md`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: Repository standards
- Produces: Complete onboarding docs, Docker setup with FFmpeg.

- [ ] **Step 1: Create `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`**
- [ ] **Step 2: Create production `Dockerfile` and `docker-compose.yml`**
- [ ] **Step 3: Update `README.md` to reference testing, Docker, and contributing guides**
- [ ] **Step 4: Commit changes**

---

### Task 7: GitHub CI/CD & Automation

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/pull_request_template.md`

**Interfaces:**
- Consumes: GitHub Actions runner
- Produces: Automated CI matrix testing, Dependabot alerts, issue templates.

- [ ] **Step 1: Create `.github/workflows/ci.yml` (Ruff lint + Pytest + pip-audit)**
- [ ] **Step 2: Create `.github/dependabot.yml` and templates in `.github/ISSUE_TEMPLATE/` & `.github/pull_request_template.md`**
- [ ] **Step 3: Commit changes**

---

### Task 8: Full Verification, Ruff Linting & Final Audit

**Files:**
- All repository files

**Interfaces:**
- Consumes: Entire codebase
- Produces: Zero lint errors, 100% test pass rate, clean security scan.

- [ ] **Step 1: Run `ruff check . --fix` and `ruff format .`**
- [ ] **Step 2: Run full pytest test suite with coverage: `pytest --cov=utils --cov=cogs`**
- [ ] **Step 3: Run `pip-audit` to confirm zero known vulnerabilities**
- [ ] **Step 4: Final commit and summary walkthrough**
