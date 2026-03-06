# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Instagram DM Pro - a desktop app (PyInstaller) for Instagram hashtag crawling, user analysis, and automated DM sending. Built with Python + NiceGUI (web UI) + Selenium (browser automation). Distributed as Windows `.exe` and macOS `.dmg`.

## Run & Build Commands

```bash
# Local development
python start.py                    # Auto-creates venv, installs deps, launches app
# Or manually:
pip install -r requirements_service.txt
python -m insta_service.main

# Build executable
python build.py                    # PyInstaller --onedir --windowed

# Release (triggers CI build + tufup signing)
git tag v1.0.X && git push origin v1.0.X
```

The app runs a NiceGUI web server on `http://localhost:8080`.

## Architecture

```
start.py → insta_service/main.py → init_db() + run_dashboard()

insta_service/
  config.py          # YAML config loader, path constants (BASE_DIR, DATA_DIR, DB_PATH)
  main.py            # Entry: init DB, backup, start dashboard
  core/
    browser.py       # undetected_chromedriver management, _chrome_create_lock
    crawler.py       # HashtagCrawler - scroll + extract usernames
    analyzer.py      # Profile scraping (followers, bio, etc.)
    dm_sender.py     # DM automation with typo simulation + rate limiting
    account_manager.py  # Account CRUD + password encryption
    scheduler.py     # APScheduler for timed crawl jobs
    updater.py       # tufup auto-update (GitHub Pages metadata + Releases targets)
  db/
    models.py        # SQLAlchemy ORM (users, accounts, dm_history, crawl_jobs, etc.)
    repository.py    # All DB queries
  ui/
    dashboard.py     # NiceGUI pages: /, /accounts, /crawl, /dm, /analyze, /settings
  license/
    validator.py     # Remote license validation + heartbeat
  utils/
    logger.py        # Rotating file + memory buffer for dashboard display
    backup.py        # SQLite auto-backup
    export.py        # Excel/CSV export
```

**Admin server** (`admin/`) is a separate FastAPI app for license management, deployed on Railway.

## Key Patterns

### Threading
- `_chrome_create_lock` (threading.Lock): Only one Chrome driver created at a time
- `_state_lock` + `_state` dict: Thread-safe global state for drivers, crawlers, login status
- Background threads for crawling/DM sending; UI on asyncio event loop

### NiceGUI
- Pages defined with `@ui.page("/path")`, async handlers supported
- Indigo theme (`#6366f1`), Quasar components
- `ui.navigate.to()` for routing, `ui.timer()` for polling

### PyInstaller Awareness
- `sys.frozen` / `sys._MEIPASS` checks throughout for path resolution
- `start.py` handles venv in dev mode, skips in frozen mode
- Windows asyncio policy: `WindowsSelectorEventLoopPolicy`

### Auto-Update (tufup)
- Metadata: `https://{owner}.github.io/{repo}/metadata/` (gh-pages)
- Targets: `https://github.com/{owner}/{repo}/releases/download/tufup-targets/`
- Trust anchor: `assets/root.json` (bundled with exe)
- Fallback: GitHub Releases API if tufup unavailable
- Splash screen on startup checks for updates before license validation

## Config

`config.yml` at project root. Loaded via `insta_service/config.py` with deep merge over defaults. Key sections: `server`, `crawling` (delays, scroll limits), `dm` (rate limits), `chrome` (headless), `selectors` (CSS selectors for Instagram DOM).

## Database

SQLite at `data/insta_service.db`. SQLAlchemy ORM in `db/models.py`. Key tables: `users`, `user_profiles`, `instagram_accounts`, `crawl_jobs`, `dm_history`, `dm_templates`, `license_info`.

## CI/CD

`.github/workflows/build-release.yml` triggers on `v*` tags:
- Windows: PyInstaller → zip → GitHub Release
- macOS: PyInstaller → DMG → GitHub Release
- tufup: Signs metadata + uploads archive (conditional on `TUFUP_PRIVATE_KEY` secret)

Version is extracted from git tag and injected into `validator.py:APP_VERSION`.

## Important Notes

- Instagram CSS selectors in `config.yml` break frequently; update `selectors` section when Instagram changes DOM
- `admin_server_url` in config.yml points to production Railway server; use `http://localhost:9090/api` for local admin testing
- Chrome profiles stored per-account in `data/chrome_profiles/` to maintain sessions
- All Korean UI text; admin server URL should not be exposed to end users
