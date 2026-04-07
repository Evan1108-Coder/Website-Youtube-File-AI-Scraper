# Detailed Setup Guide

This guide is written for someone setting up the bot from scratch on macOS.

It is intentionally step-by-step and detailed.

---

## 1. What You Are Setting Up

This project is a Discord bot that can summarize:

- public websites
- YouTube links
- uploaded documents
- images
- audio files
- video files

It can use:

- MiniMax for final summarization
- Whisper for local transcription
- Deepgram for long-file transcription if configured
- Tesseract for OCR
- local vision models for image/video understanding
- Playwright for transcript-site fallbacks
- Essentia for local music features
- optional AcoustID for song identification
- optional MIRFLEX repo integration later

---

## 2. Before You Start

You should have:

- a Mac with Terminal access
- internet access
- permission to install packages with Homebrew and `pip`
- a Discord account
- a MiniMax key and endpoint if you want the bot to actually summarize content

Optional but useful:

- a Deepgram key for long media
- a YouTube Data API key for better YouTube metadata
- an AcoustID API key if you want song ID

---

## 3. Check Whether Homebrew Is Installed

Open Terminal and run:

```bash
brew --version
```

If you get a version number, Homebrew is installed.

If you get `command not found`, install Homebrew from:

- https://brew.sh

After installation, restart Terminal and run:

```bash
brew --version
```

again.

---

## 4. Install Python 3.11

Check your Python version:

```bash
python3 --version
```

If it is older than `3.11`, install Python 3.11:

```bash
brew install python@3.11
```

Then confirm:

```bash
python3.11 --version
```

If your system still points `python3` somewhere older, you can still use the newer one by creating the virtual environment with `python3.11`.

---

## 5. Install Required System Tools

### 5A. Install FFmpeg and FFprobe

These are used for:

- media probing
- audio extraction
- video frame extraction
- AVIF fallback decode

Install:

```bash
brew install ffmpeg
```

Check:

```bash
ffmpeg -version
ffprobe -version
```

### 5B. Install Tesseract

Tesseract is used for OCR in images.

Install:

```bash
brew install tesseract
```

Check:

```bash
tesseract --version
```

### 5C. Install Chromaprint if You Want AcoustID

If you want optional song identification through AcoustID, you also need `fpcalc` from Chromaprint.

Install:

```bash
brew install chromaprint
```

Check:

```bash
fpcalc -version
```

If `fpcalc` works, AcoustID fingerprinting can work later.

### 5D. Optional: Install Node.js or Deno

If `yt-dlp` later complains about missing JavaScript runtime support for some modern YouTube extraction cases, install one of these:

```bash
brew install node
```

or

```bash
brew install deno
```

You do not always need this immediately, but it is useful if YouTube extraction starts complaining.

### 5E. Optional: Install Rust If Whisper Build Tools Are Needed

If `pip install -r requirements.txt` later complains about Rust/build tooling for `openai-whisper` dependencies:

```bash
brew install rust
```

---

## 6. Go Into the Project Folder

In Terminal:

```bash
cd "/path/to/AI Website Scraper + Summarizer V1.0 - MiniMax"
```

Replace the path with your real local path.

You can check that you are in the right place with:

```bash
ls
```

You should see things like:

- `README.md`
- `requirements.txt`
- `docs`
- `src`

---

## 7. Create and Activate a Virtual Environment

Create the venv:

```bash
python3 -m venv .venv
```

If needed, use:

```bash
python3.11 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

After activation, your prompt should show something like:

```text
(.venv)
```

at the start.

---

## 8. Install Python Dependencies

Upgrade `pip` first:

```bash
python -m pip install --upgrade pip
```

Install the project requirements:

```bash
pip install -r requirements.txt
```

If Playwright browser support is needed for DownSub / SaveSubs, install Chromium once:

```bash
playwright install chromium
```

### If You Hit a NumPy / Whisper / torch Issue

This project currently expects local Whisper to run with `numpy<2`.

If you see NumPy compatibility errors, run:

```bash
pip install "numpy<2"
pip install -r requirements.txt
```

Do **not** blindly force-reinstall everything unless you actually need to. Forced reinstalls can sometimes trigger unnecessary wheel builds.

### If You Hit an `llvmlite` Build Error

Do not immediately assume the repo is wrong. That often means `pip` tried to build `llvmlite` from source. In that situation:

- keep the pinned requirements
- avoid unnecessary `--force-reinstall`
- reinstall the normal requirements first

---

## 9. Create the `.env` File

Copy the example file:

```bash
cp .env.example .env
```

Now open `.env` in your editor.

You can use:

```bash
open -e .env
```

or edit it in VS Code.

Important:

- `.env` contains real secrets
- do **not** upload `.env` to GitHub
- keep `.env.example` shareable, but keep `.env` private

---

## 10. Fill in the Core Required `.env` Values

At minimum, these are the most important values:

```env
DISCORD_BOT_TOKEN=
MINIMAX_API_KEY=
MINIMAX_API_URL=
MINIMAX_MODEL=M2.5
```

### What Each Means

- `DISCORD_BOT_TOKEN`
  - your Discord bot token
- `MINIMAX_API_KEY`
  - your MiniMax API key
- `MINIMAX_API_URL`
  - the chat-completions-style endpoint you are using
- `MINIMAX_MODEL`
  - the model name for summarization

If these are not set, the bot cannot run properly.

---

## 11. Create a Discord Bot

1. Open:
   - https://discord.com/developers/applications
2. Click `New Application`
3. Give it a name
4. Open the application
5. Go to `Bot`
6. Click `Add Bot`
7. Under privileged intents, enable:
   - `Message Content Intent`
8. Copy the bot token
9. Put it into `.env`:

```env
DISCORD_BOT_TOKEN=your_real_discord_bot_token
```

### Invite the Bot to Your Server

1. In the Developer Portal, open:
   - `OAuth2` -> `URL Generator`
2. Under scopes, check:
   - `bot`
3. Under permissions, check at least:
   - `View Channels`
   - `Send Messages`
   - `Read Message History`
   - `Attach Files`
4. Copy the generated URL
5. Open it
6. Choose your server
7. Authorize the bot

---

## 12. Set Up MiniMax

This project expects a chat-completions-style HTTP endpoint for summarization.

In `.env`, fill:

```env
SUMMARIZER_PROVIDER=minimax_http
MINIMAX_API_KEY=your_real_minimax_key
MINIMAX_API_URL=https://your_real_minimax_chat_endpoint
MINIMAX_MODEL=your_real_model_name
```

If MiniMax is not configured correctly, the bot can start but it will fail when trying to generate real summaries.

---

## 13. Optional: Set Up Deepgram

Deepgram is optional.

It is only used when:

- media is longer than the local transcription threshold
- and `DEEPGRAM_API_KEY` is present

Put this in `.env` if you want it:

```env
DEEPGRAM_API_KEY=your_real_deepgram_key
DEEPGRAM_MODEL=nova-3
```

If you want everything local:

- leave `DEEPGRAM_API_KEY` empty
- local Whisper will handle media instead

---

## 14. Configure Local Whisper Behavior

In `.env`:

```env
WHISPER_MODEL=base
LOCAL_TRANSCRIBE_MAX_MINUTES=15
```

What this means:

- short or medium local files use Whisper locally
- if a file is longer than `LOCAL_TRANSCRIBE_MAX_MINUTES`, the bot can switch to Deepgram if Deepgram is configured

If your machine gets hot or slow:

- lower `LOCAL_TRANSCRIBE_MAX_MINUTES`

If you want to rely more on local Whisper:

- raise `LOCAL_TRANSCRIBE_MAX_MINUTES`

---

## 15. Optional: Set Up the YouTube Data API

This is optional but recommended.

It is used for:

- title
- channel
- duration
- publish date
- description

It is **not** the main transcript path.

### Step-by-step

1. Open:
   - https://console.cloud.google.com/
2. Create a dedicated Google Cloud project for this bot, or choose one you want to use
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
10. Copy the new key
11. Put it in `.env`:

```env
YOUTUBE_DATA_API_KEY=your_real_youtube_data_api_key
```

### Recommended Key Restrictions

Inside Google Cloud:

- restrict the key to `YouTube Data API v3`
- if possible, add IP restrictions for the machine/network running the bot

If you do not want to use it yet:

- leave `YOUTUBE_DATA_API_KEY=` empty

The bot can still fall back to simpler metadata lookup.

---

## 16. Understand the Current YouTube Flow

The bot currently tries YouTube in this order:

1. optional `YouTube Data API` metadata
2. `youtube-transcript-api`
3. `yt-dlp` subtitle attempt
4. `DownSub + Playwright`
5. `SaveSubs + Playwright`
6. metadata fallback

This means:

- transcript extraction does not depend on only one method
- if `yt-dlp` is blocked, the bot can still try transcript-site fallbacks
- if all transcript attempts fail, the bot can still return metadata

### Recommended YouTube `.env` Values

```env
YOUTUBE_COOKIE_MODE_ENABLED=false
YOUTUBE_COOKIES_FROM_BROWSER=
YOUTUBE_COOKIES_BROWSER_PROFILE=
YOUTUBE_COOKIES_FILE=
YOUTUBE_REQUIRE_BROWSER_PROFILE_FOR_COOKIES=true
YOUTUBE_DATA_API_KEY=
YOUTUBE_TRANSCRIPT_API_TIMEOUT_SECONDS=5
YOUTUBE_YTDLP_TIMEOUT_SECONDS=10
YOUTUBE_DOWNSUB_ENABLED=true
YOUTUBE_DOWNSUB_TIMEOUT_SECONDS=45
YOUTUBE_SAVESUBS_ENABLED=true
YOUTUBE_SAVESUBS_TIMEOUT_SECONDS=45
YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true
YOUTUBE_TRANSCRIPT_SITE_BROWSER_CHANNEL=chrome
YOUTUBE_MIN_REQUEST_INTERVAL_SECONDS=8
YOUTUBE_SLEEP_INTERVAL_SECONDS=5
YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS=15
YOUTUBE_AUTH_GATE_COOLDOWN_MINUTES=30
YOUTUBE_AUTH_GATE_GLOBAL_THRESHOLD=3
YOUTUBE_AUTH_GATE_GLOBAL_COOLDOWN_MINUTES=180
YOUTUBE_RESULT_CACHE_MINUTES=180
YOUTUBE_TRANSCRIPT_WINDOW_SECONDS=150
```

### What These Mean

- `YOUTUBE_COOKIE_MODE_ENABLED`
  - explicit opt-in for cookies
- `YOUTUBE_TRANSCRIPT_API_TIMEOUT_SECONDS`
  - short timeout for `youtube-transcript-api`
- `YOUTUBE_YTDLP_TIMEOUT_SECONDS`
  - short timeout for `yt-dlp`
- `YOUTUBE_DOWNSUB_ENABLED`
  - enable DownSub fallback
- `YOUTUBE_SAVESUBS_ENABLED`
  - enable SaveSubs fallback
- `YOUTUBE_TRANSCRIPT_SITE_HEADLESS`
  - keep transcript-site browsers invisible
- `YOUTUBE_SLEEP_INTERVAL_SECONDS` and `YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS`
  - gentler pacing around YouTube attempts
- cooldown settings
  - protect the bot from hammering blocked YouTube paths

### Recommended Safe Default

Leave cookie mode off unless you deliberately want to enable it later.

---

## 17. Set Up Local Vision

The default local vision settings are already in `.env.example`:

```env
ENABLE_LOCAL_VISION=true
VISION_CAPTION_MODEL=Salesforce/blip-image-captioning-base
VISION_OBJECT_MODEL=facebook/detr-resnet-50
```

This allows:

- image descriptions
- simple object detection
- support for local video frame review

The first run may download local model weights. That can take time.

---

## 18. Set Up Music Detection

Music detection has three layers in the current architecture:

1. `Essentia`
2. optional `AcoustID`
3. optional `MIRFLEX`

### Recommended Basic Music Settings

```env
ENABLE_MUSIC_DETECTION=true
MUSIC_ANALYSIS_SAMPLE_SECONDS=90
MUSIC_ESSENTIA_ENABLED=true
MUSIC_ACOUSTID_ENABLED=false
MUSIC_ACOUSTID_API_KEY=
MUSIC_ACOUSTID_TIMEOUT_SECONDS=20
MUSIC_FPCALC_BINARY=fpcalc
MUSIC_MIRFLEX_ENABLED=false
MUSIC_MIRFLEX_REPO_PATH=
```

### What This Means

- `Essentia` can run locally without needing an API key
- `AcoustID` is optional and needs a key
- `MIRFLEX` is optional and needs a local repo path

Important:

- if one music stage fails, the rest should still continue
- MIRFLEX is currently treated as a non-blocking optional hook

---

## 19. Optional: Set Up AcoustID

AcoustID is the optional song identification layer.

It uses:

- local fingerprinting through `fpcalc`
- an AcoustID API lookup key

### 19A. Make Sure `fpcalc` Exists

Install Chromaprint if you have not already:

```bash
brew install chromaprint
```

Check:

```bash
fpcalc -version
```

### 19B. Create an AcoustID Account

Open:

- https://acoustid.org/

Create an account or sign in.

### 19C. Create an Application

Open:

- https://acoustid.org/my-applications

Register a new application.

Suggested values:

- application name:
  - `AI Website Scraper + Summarizer`
- version:
  - `1.0`

You want the application/client key for lookup use.

### 19D. Add the Key to `.env`

```env
MUSIC_ACOUSTID_ENABLED=true
MUSIC_ACOUSTID_API_KEY=your_real_acoustid_key
MUSIC_ACOUSTID_TIMEOUT_SECONDS=20
MUSIC_FPCALC_BINARY=fpcalc
```

If you do not want AcoustID yet:

- leave `MUSIC_ACOUSTID_ENABLED=false`

### 19E. Important Notes

- AcoustID is not fully local because the final match lookup uses the AcoustID service
- but it is still a good fit for a mostly free/local-friendly setup

---

## 20. Optional: Set Up MIRFLEX

MIRFLEX is not a normal pip dependency in this project.

It is treated as:

- a separate local repo/workflow
- an optional hook path

### 20A. Get the MIRFLEX Repo

The official repo is:

- https://github.com/AMAAI-Lab/mirflex

Clone it somewhere on your machine:

```bash
cd /Users/yourname
git clone https://github.com/AMAAI-Lab/mirflex.git
```

Example local path after cloning:

```text
/Users/yourname/mirflex
```

### 20B. Set the Repo Path in `.env`

```env
MUSIC_MIRFLEX_ENABLED=true
MUSIC_MIRFLEX_REPO_PATH=/Users/yourname/mirflex
```

### 20C. Important Honest Note

At the moment, this project treats MIRFLEX as:

- optional
- non-blocking
- repo-detected

That means:

- the rest of music detection should still continue if MIRFLEX is missing or broken
- but MIRFLEX still needs its own setup, config, and likely model files inside that repo before it can do real inference

So setting the path is necessary, but not always sufficient by itself.

---

## 21. Review the Video Scan Settings

These control local video visual analysis:

```env
VIDEO_SCAN_BASE_INTERVAL_SECONDS=3
VIDEO_SCAN_MAX_INTERVAL_SECONDS=25
```

What they mean:

- review starts around `3` seconds
- calm sections can stretch up to `25` seconds
- the current system is adaptive, not a fixed dense frame cap

---

## 22. Start the Bot

Make sure your virtual environment is active, then run:

```bash
PYTHONPATH=src python -m ai_scraper_bot.main
```

You should see startup logs and then a ready message.

---

## 23. Test the Bot in Discord

### Test Simple Chat

Send something simple like:

```text
Hello?
```

The bot should respond quickly.

### Test Website Summarization

Send:

```text
Can you summarize this website? https://example.com
```

### Test YouTube

Send:

```text
Can you summarize this video? https://www.youtube.com/watch?v=VIDEO_ID
```

### Test Image Upload

Upload an image and ask:

```text
Tell me about this picture
```

### Test Audio Upload

Upload an audio file and ask:

```text
Summarize this please
```

### Test Video Upload

Upload a `.mp4` or `.mov` and ask:

```text
Can you tell me about this clip?
```

---

## 24. Understand Common Behaviors

### If a Video Has No Audio

Some videos are silent and contain no audio stream.

In that case:

- transcript-based audio analysis will not run
- visual review can still run
- music analysis can only run if an audio stream actually exists

### If YouTube Is Blocked

The bot can still:

- try transcript-site fallbacks
- return metadata fallback if needed

### If OCR Is Weak

OCR quality depends on:

- image sharpness
- contrast
- text size
- stylization

### If DownSub / SaveSubs Need Browser Support

Make sure this was run:

```bash
playwright install chromium
```

### If Whisper Is Slow

Lower:

```env
LOCAL_TRANSCRIBE_MAX_MINUTES=15
```

or configure Deepgram.

---

## 25. Share the Project Safely

Before uploading to GitHub:

Do **not** publish:

- `.env`
- `.venv`
- browser cookies
- downloaded test files
- real media in the downloads folder
- any real API keys

Your `.gitignore` should keep these out, but still double-check manually.

Good shareable files:

- `README.md`
- `requirements.txt`
- `docs/`
- `src/`
- `.env.example`
- `.gitignore`

---

## 26. Quick Checklist

Before running the bot, confirm:

- Homebrew works
- Python 3.11 works
- `ffmpeg` works
- `ffprobe` works
- `tesseract` works
- venv is activated
- `pip install -r requirements.txt` succeeded
- `playwright install chromium` succeeded
- `.env` exists
- Discord token is filled in
- MiniMax key and URL are filled in

Optional checklist:

- Deepgram key added
- YouTube Data API key added
- `fpcalc` installed
- AcoustID key added
- MIRFLEX repo cloned and path added

---

## 27. Main `.env` Reference Block

Here is the current reference block:

```env
DISCORD_BOT_TOKEN=

SUMMARIZER_PROVIDER=minimax_http
MINIMAX_API_KEY=
MINIMAX_API_URL=
MINIMAX_MODEL=M2.5

DEEPGRAM_API_KEY=
DEEPGRAM_MODEL=nova-3

WHISPER_MODEL=base
LOCAL_TRANSCRIBE_MAX_MINUTES=15

BOT_PREFIX=!summarize
MAX_CONCURRENT_JOBS=3
MESSAGE_CHUNK_SIZE=1900
DOWNLOADS_DIR=Download Audio File For AI
TEMP_SWEEP_HOURS=6
MAX_FILE_SIZE_MB=200
REPLY_TO_ALL_SERVER_MESSAGES=true

ENABLE_LOCAL_VISION=true
VISION_CAPTION_MODEL=Salesforce/blip-image-captioning-base
VISION_OBJECT_MODEL=facebook/detr-resnet-50

ENABLE_MUSIC_DETECTION=true
MUSIC_ANALYSIS_SAMPLE_SECONDS=90
MUSIC_ACOUSTID_ENABLED=false
MUSIC_ACOUSTID_API_KEY=
MUSIC_ACOUSTID_TIMEOUT_SECONDS=20
MUSIC_FPCALC_BINARY=fpcalc
MUSIC_ESSENTIA_ENABLED=true
MUSIC_MIRFLEX_ENABLED=false
MUSIC_MIRFLEX_REPO_PATH=

YOUTUBE_COOKIE_MODE_ENABLED=false
YOUTUBE_COOKIES_FROM_BROWSER=
YOUTUBE_COOKIES_BROWSER_PROFILE=
YOUTUBE_COOKIES_FILE=
YOUTUBE_REQUIRE_BROWSER_PROFILE_FOR_COOKIES=true
YOUTUBE_DATA_API_KEY=
YOUTUBE_TRANSCRIPT_API_TIMEOUT_SECONDS=5
YOUTUBE_YTDLP_TIMEOUT_SECONDS=10
YOUTUBE_DOWNSUB_ENABLED=true
YOUTUBE_DOWNSUB_TIMEOUT_SECONDS=45
YOUTUBE_SAVESUBS_ENABLED=true
YOUTUBE_SAVESUBS_TIMEOUT_SECONDS=45
YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true
YOUTUBE_TRANSCRIPT_SITE_BROWSER_CHANNEL=chrome
YOUTUBE_MIN_REQUEST_INTERVAL_SECONDS=8
YOUTUBE_SLEEP_INTERVAL_SECONDS=5
YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS=15
YOUTUBE_AUTH_GATE_COOLDOWN_MINUTES=30
YOUTUBE_AUTH_GATE_GLOBAL_THRESHOLD=3
YOUTUBE_AUTH_GATE_GLOBAL_COOLDOWN_MINUTES=180
YOUTUBE_RESULT_CACHE_MINUTES=180
YOUTUBE_TRANSCRIPT_WINDOW_SECONDS=150

VIDEO_SCAN_BASE_INTERVAL_SECONDS=3
VIDEO_SCAN_MAX_INTERVAL_SECONDS=25
```

---

## 28. Run Command Reminder

When everything is ready:

```bash
cd "/path/to/AI Website Scraper + Summarizer V1.0 - MiniMax"
source .venv/bin/activate
PYTHONPATH=src python -m ai_scraper_bot.main
```

That is the main command sequence you will use most often.
