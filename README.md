# AI Media Studio — Desktop App (v1.0.0)

A native desktop app for macOS and Windows that wraps the AI Website Scraper + Summarizer in an Electron shell. Same powerful AI pipeline, but as a standalone app with drag-and-drop file support.

It supports multiple AI providers through [LiteLLM](https://docs.litellm.ai/), including OpenAI, Anthropic, Google Gemini, Together AI (Llama), and MiniMax.

## Download

Get the latest release from the [Releases page](https://github.com/Evan1108-Coder/Website-Youtube-File-AI-Scraper/releases).

| Platform | File |
|----------|------|
| macOS (Apple Silicon — M1/M2/M3/M4) | `AI-Media-Studio-1.0.0-macOS-Apple-Silicon.dmg` |
| macOS (Intel) | `AI-Media-Studio-1.0.0-macOS-Intel.dmg` |
| Windows (64-bit) | `AI-Media-Studio-Setup-1.0.0-Windows-x64.exe` |

## Desktop App Features

Everything from the web version, plus:

- **Native app** — launches from Applications/Start Menu, has its own dock icon
- **Drag-and-drop** — drop files directly onto the window to analyze them
- **Auto-starts backend** — no need to manually run a Python server
- **Hidden inset titlebar** (macOS) — clean, modern appearance
- **Persistent storage** — database and downloads stored in user-writable locations

## Screenshots

### Workspace — Multi-Chat Interface with Document Analysis

![Workspace UI — PDF analysis conversation](docs/images/scraper-ui.png)

*The main workspace showing sidebar chat management, hero banner, chat area with an AI-summarized research paper, and the input bar with file attachment.*

### YouTube Video Analysis

![YouTube analysis — transcript extraction and summary](docs/images/youtube-analysis.png)

*A YouTube link is pasted in chat and the AI extracts the transcript, summarizes key points, and answers follow-up questions.*

### Website Scraping + File Comparison

![Website scrape and file upload comparison](docs/images/website-file-analysis.png)

*A website is scraped and summarized, then a PDF is uploaded and compared against the article — showing multi-step analysis in a single chat.*

## Diagrams

### System Architecture

![System Architecture](docs/images/architecture.png)

*Three-layer architecture: Web UI communicates with a FastAPI server that dispatches work to specialized extractors (web, YouTube, documents, vision, audio, music) and routes LLM calls through LiteLLM to five AI providers.*

### Processing Pipeline

![Processing Pipeline](docs/images/processing-pipeline.png)

*How different input types (URLs, YouTube links, documents, images, audio, video) flow through layered extraction with fallback chains, converging into a final LiteLLM summary stored in per-chat SQLite memory.*

## Supported AI Models

Set `TEXT_AI_MODEL` in your `.env` to any of these:

| Model | Provider |
|---|---|
| `gpt-5.4-pro` | OpenAI |
| `gpt-5.4-mini` | OpenAI |
| `gpt-4o` | OpenAI |
| `gpt-4o-mini` | OpenAI |
| `claude-opus-4-6` | Anthropic |
| `claude-sonnet-4-6` | Anthropic |
| `claude-haiku-4-5` | Anthropic |
| `claude-3.5-sonnet` | Anthropic |
| `gemini-3.1-pro` | Google |
| `gemini-3-flash` | Google |
| `gemini-2.5-flash-lite` | Google |
| `llama-4-maverick` | Together AI |
| `llama-4-scout` | Together AI |
| `llama-3.3-70b` | Together AI |
| `minimax-m2.7` | MiniMax |
| `minimax-m2.5-lightning` | MiniMax |

You can also pass any [LiteLLM-compatible model string](https://docs.litellm.ai/docs/providers) directly.

## What This Website Can Do

- normal AI chat with memory per chat
- multiple chats in a left sidebar
- rename, clear, delete, and clear-all chat controls
- upload files directly in the browser
- summarize websites
- summarize YouTube links
- analyze documents
- analyze images
- analyze audio files
- analyze video files

The website is designed to feel like a normal AI chat screen, but with the project's existing multimodal extraction pipeline behind it.

## Current Website Features

### Chat Workspace

- multi-chat sidebar
- chat limit of 10
- per-chat memory
- per-chat drafts and attachment state
- pause button while the AI is working
- local persistent history through SQLite
- banner hide/show toggle

### Supported Inputs

The website can work with:

- websites
- YouTube links
- text questions
- uploaded documents
- uploaded images
- uploaded audio
- uploaded video

Supported file types include:

- text and markup:
  - `.txt`, `.md`, `.csv`, `.json`, `.html`, `.xml`
- documents:
  - `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.rtf`
- images:
  - `.png`, `.jpg`, `.jpeg`, `.avif`
- audio:
  - `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`
- video:
  - `.mp4`, `.mov`

## Core Extraction Pipeline

The project tries to avoid dead-end failures by using layered extraction.

### Websites

- page text extraction
- related useful URL collection
- image review when relevant
- directly downloadable website-video review when possible
- final summary focused on the subject matter, not just page structure

### YouTube

The current YouTube flow is transcript-first:

1. optional `YouTube Data API` metadata
2. `youtube-transcript-api`
3. `yt-dlp` subtitle attempt
4. `DownSub + Playwright`
5. `SaveSubs + Playwright`
6. metadata fallback

That means the app can still give something useful even if direct YouTube access is partially blocked.

### Images and Video Frames

The active visual-description path uses your configured AI model.

That means:

- image descriptions come from your AI model
- video key-frame descriptions come from your AI model
- the older BLIP caption path is no longer the normal active description flow

### Audio and Video

The media pipeline can separate:

- transcript / speech analysis
- visual analysis
- music analysis

So a silent video can still be reviewed visually, and a music-heavy file can still produce music analysis even if speech transcription is weak.

### Music Analysis

The music layer is free/local-friendly by default:

- `Essentia`
  - local music features such as BPM, key, and loudness-like values
- `AcoustID`
  - optional song ID using local fingerprinting plus an API key
- `MIRFLEX`
  - optional repo hook for future music tagging/classification extensions

Important:

- `Essentia` is the default main music feature layer
- `AcoustID` is optional
- `MIRFLEX` is optional
- if one music stage fails, the others should still continue

## Honesty and Failure Handling

This project tries to stay honest about what actually happened.

It carries extra runtime and extraction context into the summary pipeline, including things like:

- which YouTube path actually succeeded
- which music libraries were attempted
- which music libraries produced output
- recent runtime diary lines
- which media was actually reviewed

That helps reduce fake claims like saying a fallback worked when it did not.

## Main Files

Most important files for the website version:

- website entrypoint:
  - `src/ai_scraper_bot/webapp.py`
- web backend:
  - `src/ai_scraper_bot/web/service.py`
  - `src/ai_scraper_bot/web/store.py`
- web frontend:
  - `src/ai_scraper_bot/web/static/index.html`
  - `src/ai_scraper_bot/web/static/app.css`
  - `src/ai_scraper_bot/web/static/app.js`
- shared config:
  - `src/ai_scraper_bot/config.py`
- shared prompts:
  - `src/ai_scraper_bot/prompts.py`
- summarizer / LiteLLM integration:
  - `src/ai_scraper_bot/services/summarizer.py`
- YouTube extraction:
  - `src/ai_scraper_bot/services/youtube.py`
- website extraction:
  - `src/ai_scraper_bot/services/website.py`
- transcript-site fallbacks:
  - `src/ai_scraper_bot/services/downsub.py`
  - `src/ai_scraper_bot/services/savesubs.py`
- transcription:
  - `src/ai_scraper_bot/services/transcription.py`
- local video analysis:
  - `src/ai_scraper_bot/services/video_analysis.py`
- local vision:
  - `src/ai_scraper_bot/services/vision.py`
- local music analysis:
  - `src/ai_scraper_bot/services/music_analysis.py`
- file parsing:
  - `src/ai_scraper_bot/parsers/file_parser.py`

## Installation (Desktop App)

### macOS

1. Download the `.dmg` for your chip (Apple Silicon or Intel)
2. Open the DMG and drag **AI Media Studio** to Applications
3. On first launch, right-click the app → **Open** (to bypass Gatekeeper — the app is unsigned)
4. The app will auto-start the Python backend

### Windows

1. Download the `.exe` installer
2. Run the installer and follow the prompts
3. Launch **AI Media Studio** from the Start Menu

### Prerequisites

- **Python 3.10+** installed and available in PATH
- Python dependencies installed: `pip install -r requirements.txt`
- System tools: `ffmpeg`, `tesseract` (for audio/OCR features)
- Playwright Chromium: `playwright install chromium` (for website scraping)
- `.env` file with your AI API keys (see `.env.example`)

### Where the app stores data

- Database: `~/Library/Application Support/ai-media-studio/webapp.sqlite` (macOS) or `%APPDATA%/ai-media-studio/webapp.sqlite` (Windows)
- Downloads: `~/Documents/AI Media Studio Downloads/`

## Development (Run from Source)

The full setup guide is in [docs/SETUP.md](docs/SETUP.md).

```bash
# Install dependencies
pip install -r requirements.txt
npm install

# Run the Electron app in dev mode
npm start

# Or run just the web server
PYTHONPATH=src python -m ai_scraper_bot.webapp
```

The web server runs at `http://127.0.0.1:8000` by default (or port 18919 when launched via Electron).

## Building Installers

```bash
# macOS (arm64 + x64)
npm run build:mac

# Windows (x64)
npm run build:win

# Both platforms
npm run build:all
```

Output goes to `dist-electron/`.

## Recommended Defaults

If you want a solid default setup:

- `ENABLE_LOCAL_VISION=true`
- `ENABLE_MUSIC_DETECTION=true`
- `MUSIC_ESSENTIA_ENABLED=true`
- `MUSIC_ACOUSTID_ENABLED=false` until AcoustID is configured
- `MUSIC_MIRFLEX_ENABLED=false` until MIRFLEX is actually set up
- `YOUTUBE_COOKIE_MODE_ENABLED=false`
- `YOUTUBE_DOWNSUB_ENABLED=true`
- `YOUTUBE_SAVESUBS_ENABLED=true`
- `YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true`

## Privacy and Sharing Notes

Before sharing or publishing, do **not** expose:

- `.env`
- `.venv`
- downloaded test media
- cookies files
- browser profile exports
- real API keys
- local machine-specific secrets

The repo is meant to keep those out through `.gitignore`, but you should still double-check before uploading.

## Troubleshooting Notes

### YouTube still fails

That does not always mean the whole app is broken. Check which stage actually failed:

- `youtube-transcript-api`
- `yt-dlp`
- `DownSub`
- `SaveSubs`
- metadata fallback

### Audio transcription fails with NumPy / torch issues

The local Whisper setup is currently intended to run with `numpy<2`.

### A video has no audio

Some `.mp4` or `.mov` files are silent. In that case:

- transcript-based audio analysis will not run
- visual review can still run
- music analysis can only run if an audio stream actually exists

### MIRFLEX is enabled but not working

The current code treats MIRFLEX as an optional repo hook. The rest of the music chain should still continue even if MIRFLEX itself is not fully wired.

## Full Setup

For the exact detailed installation and configuration flow, read [docs/SETUP.md](docs/SETUP.md).

For a complete reference of every environment variable, see [ENVREADME.md](ENVREADME.md).
