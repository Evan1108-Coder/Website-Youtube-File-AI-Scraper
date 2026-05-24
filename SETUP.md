# Website Setup Guide

This guide is for the website version of the project.

It is written for someone setting it up locally on macOS from scratch.

The website is the main interface in this version, and this guide is focused on getting the local web app running well.

## 1. What You Are Setting Up

You are setting up a local website that can:

- chat with AI
- keep separate chat histories
- upload files
- summarize websites
- summarize YouTube links
- inspect images
- inspect audio
- inspect video
- keep local chat history in SQLite

It uses [LiteLLM](https://docs.litellm.ai/) to support multiple AI providers:

- **OpenAI** (GPT-5.4, GPT-4o, etc.)
- **Anthropic** (Claude Opus, Sonnet, Haiku)
- **Google Gemini** (Gemini 3.1 Pro, 3 Flash, etc.)
- **Together AI** (Llama 4, Llama 3.3, etc.)
- **MiniMax** (M2.7, M2.5 Lightning)

The website uses the same shared extraction engine underneath as the Discord version.

## 2. What You Need

Required:

- a Mac with Terminal access
- internet access
- permission to install packages with Homebrew and `pip`
- an API key from your chosen AI provider (OpenAI, Anthropic, Google, Together AI, or MiniMax)

Optional but recommended:

- a YouTube Data API key
- a cloud audio transcription API key (OpenAI or Deepgram)
- an AcoustID API key
- a local MIRFLEX repo if you want to experiment with that path

## 3. Install Homebrew If Needed

Check:

```bash
brew --version
```

If that says `command not found`, install Homebrew from:

- https://brew.sh

Then restart Terminal and run:

```bash
brew --version
```

again.

## 4. Install Python 3.11

Check your version:

```bash
python3 --version
```

This project should be run with Python `3.11`.

If needed:

```bash
brew install python@3.11
```

Then confirm:

```bash
python3.11 --version
```

## 5. Install Required System Tools

### 5A. FFmpeg

Used for:

- media probing
- audio extraction
- video frame extraction
- some image/video fallbacks

Install:

```bash
brew install ffmpeg
```

Check:

```bash
ffmpeg -version
ffprobe -version
```

### 5B. Tesseract

Used for OCR in images.

Install:

```bash
brew install tesseract
```

Check:

```bash
tesseract --version
```

### 5C. Chromaprint for AcoustID

Only needed if you want optional AcoustID song identification.

Install:

```bash
brew install chromaprint
```

Check:

```bash
fpcalc -version
```

### 5D. Optional: Node.js or Deno

Sometimes useful if `yt-dlp` complains about modern JavaScript runtime support:

```bash
brew install node
```

or

```bash
brew install deno
```

### 5E. Optional: Rust

Only needed if a Python package later complains about Rust-based build tooling:

```bash
brew install rust
```

## 6. Go Into the Project Folder

```bash
cd "/path/to/project"
```

Check:

```bash
ls
```

You should see:

- `README.md`
- `requirements.txt`
- `docs`
- `src`

## 7. Create and Activate the Virtual Environment

Create it with Python 3.11:

```bash
python3.11 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

You should now see something like:

```text
(.venv)
```

at the start of the Terminal prompt.

## 8. Install Python Dependencies

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

Install requirements:

```bash
pip install -r requirements.txt
```

Install Playwright Chromium once:

```bash
playwright install chromium
```

The website stack also depends on:

- `fastapi`
- `uvicorn`
- `python-multipart`

Those are already included in `requirements.txt`.

### If You Hit a NumPy / Whisper / torch Issue

This project currently expects local Whisper to run with `numpy<2`.

If you see compatibility errors:

```bash
pip install "numpy<2"
pip install -r requirements.txt
```

### If You Hit an `llvmlite` Build Error

Do not immediately force-reinstall everything. First try the normal requirements install again with the pinned versions in the repo.

## 9. Create the `.env` File

Copy the example:

```bash
cp .env.example .env
```

Open it in your editor.

Example:

```bash
open -e .env
```

Important:

- `.env` contains real secrets
- do **not** upload `.env` to GitHub
- keep `.env.example` shareable

## 10. Fill In the Core Website Values

At minimum, set these:

```env
TEXT_AI_MODEL=your_chosen_model
TEXT_AI_API_KEY=your_api_key
```

### Supported Models

| Model | Provider | Where to get a key |
|---|---|---|
| `gpt-5.4-pro` | OpenAI | https://platform.openai.com/api-keys |
| `gpt-5.4-mini` | OpenAI | https://platform.openai.com/api-keys |
| `gpt-4o` | OpenAI | https://platform.openai.com/api-keys |
| `gpt-4o-mini` | OpenAI | https://platform.openai.com/api-keys |
| `claude-opus-4-6` | Anthropic | https://console.anthropic.com/ |
| `claude-sonnet-4-6` | Anthropic | https://console.anthropic.com/ |
| `claude-haiku-4-5` | Anthropic | https://console.anthropic.com/ |
| `claude-3.5-sonnet` | Anthropic | https://console.anthropic.com/ |
| `gemini-3.1-pro` | Google | https://aistudio.google.com/apikey |
| `gemini-3-flash` | Google | https://aistudio.google.com/apikey |
| `gemini-2.5-flash-lite` | Google | https://aistudio.google.com/apikey |
| `llama-4-maverick` | Together AI | https://api.together.xyz/ |
| `llama-4-scout` | Together AI | https://api.together.xyz/ |
| `llama-3.3-70b` | Together AI | https://api.together.xyz/ |
| `minimax-m2.7` | MiniMax | MiniMax dashboard |
| `minimax-m2.5-lightning` | MiniMax | MiniMax dashboard |

The system auto-detects which provider you are using based on the model name and sets the correct API key environment variable for LiteLLM.

### Example Configurations

For OpenAI:

```env
TEXT_AI_MODEL=gpt-4o
TEXT_AI_API_KEY=sk-proj-your_real_openai_key
```

For Anthropic:

```env
TEXT_AI_MODEL=claude-sonnet-4-6
TEXT_AI_API_KEY=sk-ant-your_real_anthropic_key
```

For Google Gemini:

```env
TEXT_AI_MODEL=gemini-3-flash
TEXT_AI_API_KEY=your_real_gemini_key
```

### MiniMax Special Case

If you use a MiniMax model, you also need `MINIMAX_API_URL`:

```env
TEXT_AI_MODEL=minimax-m2.7
TEXT_AI_API_KEY=your_real_minimax_key
MINIMAX_API_URL=https://your_real_minimax_chat_endpoint
```

### Legacy MiniMax Variables

If you are migrating from the original MiniMax-only version, your old variables (`MINIMAX_API_KEY`, `MINIMAX_MODEL`, etc.) still work as a fallback. But it is recommended to switch to the new `TEXT_AI_MODEL` + `TEXT_AI_API_KEY` format.

### Website Server Settings

Optional — defaults are fine for local use:

```env
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8000
WEBAPP_DB_PATH=./.webapp/webapp.sqlite
```

## 11. Optional: Configure YouTube Support

Optional but recommended:

```env
YOUTUBE_DATA_API_KEY=your_real_youtube_data_api_key
YOUTUBE_TRANSCRIPT_API_TIMEOUT_SECONDS=5
YOUTUBE_YTDLP_TIMEOUT_SECONDS=10
YOUTUBE_DOWNSUB_ENABLED=true
YOUTUBE_DOWNSUB_TIMEOUT_SECONDS=45
YOUTUBE_SAVESUBS_ENABLED=true
YOUTUBE_SAVESUBS_TIMEOUT_SECONDS=45
YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true
YOUTUBE_TRANSCRIPT_SITE_BROWSER_CHANNEL=chrome
YOUTUBE_COOKIE_MODE_ENABLED=false
```

Current YouTube order:

1. optional YouTube Data API metadata
2. `youtube-transcript-api`
3. `yt-dlp` subtitle attempt
4. `DownSub + Playwright`
5. `SaveSubs + Playwright`
6. metadata fallback

### How to Get a YouTube Data API Key

1. Open:
   - https://console.cloud.google.com/
2. Create or choose a Google Cloud project
3. Open:
   - `APIs & Services`
4. Click:
   - `Enable APIs and Services`
5. Search:
   - `YouTube Data API v3`
6. Enable it
7. Open:
   - `Credentials`
8. Click:
   - `Create Credentials`
9. Choose:
   - `API key`
10. Copy the key
11. Put it into `.env`

Recommended:

- restrict the key to `YouTube Data API v3`
- add IP restrictions if appropriate

## 12. Optional: Configure Cloud Audio Transcription

If you want cloud transcription instead of (or in addition to) local Whisper:

For OpenAI Whisper API:

```env
AUDIO_AI_MODEL=whisper-1
AUDIO_AI_API_KEY=sk-proj-your_openai_key
```

For Deepgram:

```env
AUDIO_AI_MODEL=deepgram/nova-3
AUDIO_AI_API_KEY=your_deepgram_key
```

If your audio model uses the **same provider** as your text model (e.g. both OpenAI), you can leave `AUDIO_AI_API_KEY` blank — it automatically reuses `TEXT_AI_API_KEY`.

If you want everything local, leave `AUDIO_AI_MODEL` empty.

## 13. Configure Local Whisper

Recommended starting values:

```env
WHISPER_MODEL=base
LOCAL_TRANSCRIBE_MAX_MINUTES=15
```

Meaning:

- shorter files stay local with Whisper
- longer files can switch to cloud transcription if configured

## 14. Configure Visual Analysis

Recommended:

```env
ENABLE_LOCAL_VISION=true
```

Current visual setup:

- your configured AI model handles image descriptions
- your configured AI model handles video key-frame descriptions

The older BLIP path is no longer the normal active image-description workflow.

## 15. Configure Music Detection

Recommended defaults:

```env
ENABLE_MUSIC_DETECTION=true
MUSIC_ESSENTIA_ENABLED=true
MUSIC_ACOUSTID_ENABLED=false
MUSIC_MIRFLEX_ENABLED=false
```

### AcoustID Setup

If you want optional song identification:

1. Install `chromaprint` so `fpcalc` exists
2. Open:
   - https://acoustid.org/
3. Create an account or sign in
4. Open:
   - https://acoustid.org/my-applications
5. Register an application
6. Use a simple app name like:
   - `AI Website Scraper + Summarizer`
7. Use a version like:
   - `1.0`
8. Copy the application/client key
9. Put it into `.env`

Example:

```env
MUSIC_ACOUSTID_ENABLED=true
MUSIC_ACOUSTID_API_KEY=your_real_acoustid_key
MUSIC_ACOUSTID_TIMEOUT_SECONDS=20
MUSIC_FPCALC_BINARY=fpcalc
```

### MIRFLEX Setup

MIRFLEX is optional and currently treated as a repo hook.

If you want to set it up:

1. Clone the repo somewhere on your machine:

```bash
cd /Users/yourname
git clone https://github.com/AMAAI-Lab/mirflex.git
```

2. Confirm the folder exists
3. Put the path into `.env`

Example:

```env
MUSIC_MIRFLEX_ENABLED=true
MUSIC_MIRFLEX_REPO_PATH=/Users/yourname/mirflex
```

Important:

- if MIRFLEX is missing or broken, the rest of the music chain should still continue
- MIRFLEX may still need its own repo-specific setup beyond just setting the path

## 16. Start the Website

From the project folder with `.venv` activated:

```bash
PYTHONPATH=src python -m ai_scraper_bot.webapp
```

Then open:

```text
http://127.0.0.1:8000
```

You should see:

- a left chat sidebar
- a dark local web app interface
- file upload support
- normal AI chat
- website / YouTube / file summarization in the same place

## 17. Recommended Safe Defaults

Good starting defaults:

```env
ENABLE_LOCAL_VISION=true
ENABLE_MUSIC_DETECTION=true
MUSIC_ESSENTIA_ENABLED=true
MUSIC_ACOUSTID_ENABLED=false
MUSIC_MIRFLEX_ENABLED=false
YOUTUBE_COOKIE_MODE_ENABLED=false
YOUTUBE_DOWNSUB_ENABLED=true
YOUTUBE_SAVESUBS_ENABLED=true
YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true
```

## 18. Privacy Notes

Before sharing this project publicly, do **not** expose:

- `.env`
- `.venv`
- downloaded media
- cookies
- browser profile exports
- real API keys

## 19. Troubleshooting

### The website loads but summaries fail

Check:

- `TEXT_AI_MODEL` is set
- `TEXT_AI_API_KEY` is set and valid for that provider
- the API endpoint is actually reachable

### Audio transcription fails with NumPy / torch issues

This project expects local Whisper to work with `numpy<2`.

### A video has no audio

That is not always corruption. Some video files are silent. In that case:

- transcript-based analysis will not run
- visual review can still run
- music analysis can only run if audio exists

### YouTube still fails

Check which exact stage failed:

- `youtube-transcript-api`
- `yt-dlp`
- `DownSub`
- `SaveSubs`
- metadata fallback

### MIRFLEX does not work

That does not necessarily mean the whole music system is broken. MIRFLEX is optional and the rest of the chain should still continue.

## 20. Final Note

This project is meant to keep improving. If you find bugs, weird edge cases, better design ideas, stronger extraction methods, or safer ways to structure the system, that is exactly the kind of feedback this repo is meant to invite.

For a complete reference of every environment variable, see [ENVREADME.md](../ENVREADME.md).
