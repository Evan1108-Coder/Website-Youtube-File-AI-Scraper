# AI Website Scraper + Summarizer V1.0 - MiniMax

This project is a Discord bot that can analyze and summarize:

- websites
- YouTube links
- uploaded documents
- images
- audio files
- video files

I want this project to keep improving over time, so people are very welcome to explore it, remix it, fork it, and suggest better ideas. If you find weak spots, better libraries, cleaner architecture, or safer workflows, I genuinely want to hear those improvements.

It is built around a layered extraction approach. Instead of depending on only one method, it tries the safest available path for each source type, keeps moving through fallbacks when possible, and now carries runtime notes into the final answer so the bot is less likely to guess or misrepresent what really happened.

## What It Can Do

### Websites

- extract normal page text
- collect related useful URLs from the page
- inspect selected important images
- inspect directly downloadable website-hosted videos
- summarize the content instead of only describing the page itself

### YouTube

The current YouTube path is transcript-first and safety-first:

1. optional `YouTube Data API` metadata lookup
2. `youtube-transcript-api`
3. `yt-dlp` subtitle attempt
4. `DownSub + Playwright`
5. `SaveSubs + Playwright`
6. metadata-only fallback if transcript extraction still fails

This means the bot can still give a useful result even if direct YouTube extraction fails.

### Uploaded Files

Supported types:

- text and markup:
  - `.txt`, `.md`, `.csv`, `.json`, `.html`, `.xml`
- office and document files:
  - `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.rtf`
- images:
  - `.png`, `.avif`, `.jpg`, `.jpeg`
- audio:
  - `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`
- video:
  - `.mp4`, `.mov`

### Images

- OCR with `Tesseract`
- MiniMax-based visual analysis
- AVIF support through:
  - Pillow AVIF support when available
  - `ffmpeg` fallback decoding when needed

### Audio and Video

- local Whisper transcription
- optional Deepgram for longer files
- adaptive video frame review for local videos
- optional music-aware analysis for local audio, local video, and directly downloadable website videos

### Music Detection

The music layer is designed to be free/local-friendly by default:

- `Essentia`
  - local musical features like BPM, key, and loudness-like values
- `AcoustID`
  - optional song identification using local fingerprinting plus an AcoustID lookup key
- `MIRFLEX`
  - optional local repo hook for future extended music tagging/classification

Important:

- `Essentia` is the main local/default music feature layer
- `AcoustID` is optional
- `MIRFLEX` is optional
- if one music stage fails, the rest of the music pipeline should continue

## How the Bot Tries to Stay Honest

The bot now carries extra extraction context into the summary pipeline, including things like:

- which YouTube path actually succeeded
- which music libraries were attempted
- which music libraries produced output
- runtime diary lines from the terminal process
- media that was actually reviewed

That helps reduce false claims like saying a fallback succeeded when it did not.

## Key Design Choices

### 1. Transcript-site fallbacks for YouTube

Instead of stopping at `yt-dlp` failures, the bot now keeps going through transcript-site fallbacks before giving up.

### 2. Metadata fallback instead of dead-end errors

If a YouTube transcript still cannot be recovered, the bot can still return:

- title
- channel
- publish date
- duration
- description

### 3. Audio/video/music are separated

For media files, the bot can treat these as separate evidence streams:

- transcript
- visual review
- music analysis

That means a silent video can still be reviewed visually, and a music-heavy audio file can still use the music pipeline even if speech transcription is weak.

### 4. Runtime-diary-aware answers

The bot can use recent runtime diary lines from the running app process so it has better grounding when explaining failures.

### 5. MiniMax-only visual descriptions

The active image and video-frame description path now uses `MiniMax` as the visual description engine.

That means:

- image descriptions come from MiniMax
- video key-frame descriptions come from MiniMax
- the older BLIP captioning path is no longer part of the normal visual description flow

This was changed to reduce inaccurate or noisy local captions.

## Main Project Files

If you want to inspect the code, these are the most important files:

- Discord bot logic:
  - `src/ai_scraper_bot/bot.py`
- config and env loading:
  - `src/ai_scraper_bot/config.py`
- prompts:
  - `src/ai_scraper_bot/prompts.py`
- summarizer / MiniMax HTTP integration:
  - `src/ai_scraper_bot/services/summarizer.py`
- YouTube extraction:
  - `src/ai_scraper_bot/services/youtube.py`
- website extraction:
  - `src/ai_scraper_bot/services/website.py`
- transcript-site fallbacks:
  - `src/ai_scraper_bot/services/downsub.py`
  - `src/ai_scraper_bot/services/savesubs.py`
- local transcription:
  - `src/ai_scraper_bot/services/transcription.py`
- local video analysis:
  - `src/ai_scraper_bot/services/video_analysis.py`
- local vision:
  - `src/ai_scraper_bot/services/vision.py`
- local music analysis:
  - `src/ai_scraper_bot/services/music_analysis.py`
- file parsing:
  - `src/ai_scraper_bot/parsers/file_parser.py`

## Installation Overview

The full step-by-step guide is in [docs/SETUP.md](docs/SETUP.md).

At a high level, setup looks like this:

1. install Homebrew if needed
2. install Python 3.11
3. install `ffmpeg`, `ffprobe`, and `tesseract`
4. create and activate `.venv`
5. install Python requirements
6. install Playwright Chromium
7. optionally install `chromaprint` for AcoustID
8. create `.env` from `.env.example`
9. fill in Discord + MiniMax settings
10. optionally add YouTube Data API, Deepgram, AcoustID, and MIRFLEX settings
11. run the bot

## Starting the Bot

Once setup is complete:

```bash
cd "/path/to/AI Website Scraper + Summarizer V1.0 - MiniMax"
source .venv/bin/activate
PYTHONPATH=src python -m ai_scraper_bot.main
```

If the bot starts correctly, you should see a login message and a ready message in Terminal.

## Example Environment Features

The current `.env.example` includes support for:

- Discord token
- MiniMax endpoint and model
- Deepgram
- local Whisper
- MiniMax visual analysis
- local music detection
- AcoustID
- MIRFLEX repo hook
- YouTube Data API
- YouTube pacing / cooldown / cache settings
- adaptive local video scan settings

## Recommended Defaults

If you want the safest basic setup:

- `ENABLE_LOCAL_VISION=true`
- `ENABLE_MUSIC_DETECTION=true`
- `MUSIC_ESSENTIA_ENABLED=true`
- `MUSIC_ACOUSTID_ENABLED=false` until AcoustID is configured
- `MUSIC_MIRFLEX_ENABLED=false` until a MIRFLEX repo is actually set up
- `YOUTUBE_COOKIE_MODE_ENABLED=false`
- `YOUTUBE_DOWNSUB_ENABLED=true`
- `YOUTUBE_SAVESUBS_ENABLED=true`
- `YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true`

For the current visual architecture, keep in mind:

- `ENABLE_LOCAL_VISION=true` means visual review is enabled
- the active visual description engine is `MiniMax`
- older env values like `VISION_CAPTION_MODEL` and `VISION_OBJECT_MODEL` may still exist in config for compatibility, but they are not the main active image-description path anymore

## Privacy and Sharing Notes

Before uploading this project publicly, make sure you do **not** publish:

- `.env`
- `.venv`
- downloaded test media
- cookies files
- browser profile exports
- any real API keys

This repo is intended to keep those out of Git through `.gitignore`, but you should still double-check before publishing.

## Troubleshooting Overview

### YouTube still fails

That does not always mean the whole bot is broken. Check whether:

- `youtube-transcript-api` failed
- `yt-dlp` was blocked
- `DownSub` or `SaveSubs` succeeded
- the bot fell back to metadata only

### Audio transcription fails with NumPy / torch issues

This project is currently intended to run local Whisper with `numpy<2`.

### A video has no audio

Some `.mp4` or `.mov` files are silent video files with no audio stream at all. In that case:

- transcript-based audio analysis will not run
- visual review can still run
- music analysis can only run if there is actually an audio stream

### MIRFLEX is enabled but not working

The current code treats MIRFLEX as an optional repo hook. That means:

- the rest of the music chain should still continue
- but MIRFLEX itself still needs its own repo, setup, and inference wiring

## If You Want the Full Exact Setup

Read [docs/SETUP.md](docs/SETUP.md). That guide is meant to be the detailed, step-by-step version.
