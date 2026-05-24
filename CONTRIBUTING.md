# Contributing to AI Media Studio

Thanks for your interest in contributing! This document explains how to get started.

## Branch Structure

Each branch represents a different interface for the same AI scraper/summarizer pipeline:

| Branch | Interface |
|--------|-----------|
| `master-app-interface` | Electron desktop app (macOS + Windows) |
| `master-website-interface` | Web app (FastAPI + browser) |
| `master-discord-interface` | Discord bot |

Choose the branch that matches the interface you want to work on.

## Getting Started

1. Fork the repository.
2. Clone your fork and check out the branch you want to contribute to:
   ```bash
   git clone https://github.com/<your-username>/Website-Youtube-File-AI-Scraper.git
   cd Website-Youtube-File-AI-Scraper
   git checkout master-website-interface  # or another branch
   ```
3. Follow [SETUP.md](SETUP.md) to configure your local environment.
4. Create a feature branch off the target interface branch:
   ```bash
   git checkout -b my-feature
   ```

## Development

- Python 3.11+ is required.
- Install dependencies: `pip install -r requirements.txt`
- Run the web app: `python -m ai_scraper_bot.webapp` (set env vars per SETUP.md)
- For the Electron app: `npm install && npm start`

## Pull Requests

- Open PRs against the interface branch you're targeting (not `main`).
- Keep PRs focused — one feature or fix per PR.
- Include a clear description of what changed and why.
- Make sure the app runs locally without errors before submitting.

## Code Style

- Python: follow PEP 8, use type hints where practical.
- JavaScript: use `const`/`let` (no `var`), semicolons, 2-space indent.
- Keep files focused — avoid mixing unrelated changes.

## Reporting Issues

Open an issue on GitHub with:
- Which branch/interface you're using
- Steps to reproduce
- Expected vs actual behavior
- OS and Python/Node version

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
