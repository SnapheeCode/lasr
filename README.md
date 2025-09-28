# Avtor24 Auction Bot

This project provides an MVP implementation of a browser-driven automation bot for Avtor24 auctions. The bot monitors new orders, prioritises bids, places offers through a Playwright-controlled browser, and schedules follow-up communication.

## Features

- Per-account configuration with individual filters, templates, and pacing controls.
- GraphQL client for fetching auctions, preparing orders, and sending bids/messages while reusing browser cookies to keep the session authorised.
- Priority queue that emphasises new orders while keeping the backlog fresh.
- Browser automation routines that mimic user interactions and support manual captcha solving.
- Scheduler for delayed follow-up messages and interval enforcement between bids.
- Resilient worker supervision with automatic reconnection and logging hooks.

## Project Layout

- `src/auction_bot/` — core package with modules for configuration, queue management, GraphQL access, and workers.
- `config/` — example configuration files per account.
- `pyproject.toml` — project metadata and runtime dependencies.

## Usage

1. Install dependencies and Playwright browsers:
   ```bash
   pip install -e .
   playwright install
   ```
2. Prepare account configuration files inside `config/` (copy and adapt the example file). For instance:
   ```yaml
   name: demo
   login: user@example.com
   password: secret
   filters:
     categories: ["Юриспруденция"]
     types: ["Доклад", "Статья"]
     min_budget: 500
   ```
3. Launch the bot:
   ```bash
   avtor24-bot --config-dir config
   ```

The bot starts a dedicated worker per account, opens a Playwright-controlled Chromium window for manual captcha solving, and begins monitoring auctions according to the configured filters and pacing parameters.

## Packaging

To produce a standalone executable on Windows, build the project and feed it to PyInstaller:

```bash
pip install pyinstaller
pyinstaller --name avtor24-bot --onefile -p src/ auction_bot/__main__.py
```

Include the generated executable together with the `config/` directory and instructions for the operator.
