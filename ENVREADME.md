# Environment Variables Reference

Complete guide to every `.env` variable used by the AI Website Scraper.

---

## Discord Bot

### `DISCORD_BOT_TOKEN` (required)

Your Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications). Create an application, add a bot, and copy the token.

**Example:**
```
DISCORD_BOT_TOKEN=MTIz...
```

---

## AI Model Configuration

### `TEXT_AI_MODEL` (required)

The AI model used for all text tasks: chat responses, website/YouTube summaries, file analysis, and image descriptions.

**How it works:** You provide a short model name and the system auto-detects the provider and routes the request through LiteLLM.

| Value | Provider | Notes |
|---|---|---|
| `gpt-5.4-pro` | OpenAI | Latest flagship model |
| `gpt-5.4-mini` | OpenAI | Faster, cheaper |
| `gpt-4o` | OpenAI | Strong all-rounder |
| `gpt-4o-mini` | OpenAI | Fast and cheap |
| `claude-opus-4-6` | Anthropic | Most capable Claude |
| `claude-sonnet-4-6` | Anthropic | Balanced performance/cost |
| `claude-haiku-4-5` | Anthropic | Fastest Claude |
| `claude-3.5-sonnet` | Anthropic | Previous-gen Sonnet |
| `gemini-3.1-pro` | Google | Latest Gemini Pro |
| `gemini-3-flash` | Google | Fast Gemini |
| `gemini-2.5-flash-lite` | Google | Cheapest Gemini |
| `llama-4-maverick` | Together AI | Open-source Llama 4 (large) |
| `llama-4-scout` | Together AI | Open-source Llama 4 (medium) |
| `llama-3.3-70b` | Together AI | Open-source Llama 3.3 |
| `minimax-m2.7` | MiniMax | MiniMax M2.7 |
| `minimax-m2.5-lightning` | MiniMax | MiniMax M2.5 Lightning |

You can also pass any LiteLLM-compatible model string directly (e.g. `anthropic/claude-sonnet-4-6`).

**Example:**
```
TEXT_AI_MODEL=gpt-4o
```

---

### `TEXT_AI_API_KEY` (required)

The API key for the provider of your chosen `TEXT_AI_MODEL`. The system auto-detects which provider environment variable to set:

| Model prefix | Provider key set |
|---|---|
| `gpt-*` (no prefix) | `OPENAI_API_KEY` |
| `claude-*` → `anthropic/` | `ANTHROPIC_API_KEY` |
| `gemini-*` → `gemini/` | `GEMINI_API_KEY` |
| `llama-*` → `together_ai/` | `TOGETHER_AI_API_KEY` |
| `minimax-*` → `minimax/` | Passed directly to LiteLLM (also needs `MINIMAX_API_URL`) |

You only need **one** API key — the one for your chosen model's provider. The system handles the rest.

**Example:**
```
TEXT_AI_API_KEY=sk-proj-abc123...
```

---

### `AUDIO_AI_MODEL` (optional)

Cloud-based audio transcription model. If not set, the system uses local Whisper (free, runs on your machine).

| Value | Provider | Notes |
|---|---|---|
| `whisper-1` | OpenAI | OpenAI's Whisper API |
| `deepgram/nova-3` | Deepgram | Fast, accurate, latest |
| `deepgram/nova-2` | Deepgram | Previous generation |
| `deepgram/whisper-large` | Deepgram | Deepgram-hosted Whisper |

**When to use:** Set this if local Whisper is too slow, you don't have enough RAM/CPU, or you need higher accuracy. Otherwise, leave it blank and the system uses local Whisper for free.

**Example:**
```
AUDIO_AI_MODEL=whisper-1
```

---

### `AUDIO_AI_API_KEY` (optional)

API key for the `AUDIO_AI_MODEL` provider. If your audio model uses the **same provider** as your text model (e.g. both OpenAI), you can leave this blank — it automatically reuses `TEXT_AI_API_KEY`.

Only set this if your audio provider is **different** from your text provider (e.g. text uses Claude but audio uses Deepgram).

**Example:**
```
AUDIO_AI_API_KEY=your_deepgram_key_here
```

---

## Music Detection

### `MUSIC_ACOUSTID_API_KEY` (optional)

API key for [AcoustID](https://acoustid.org/) music fingerprinting. Used to identify songs by their audio fingerprint. Get a free key at https://acoustid.org/new-application.

**Effect:** When set and `MUSIC_ACOUSTID_ENABLED=true`, the bot can identify songs by name, artist, and album using audio fingerprinting. Without it, music detection relies only on local analysis (Essentia/MIRFLEX).

**Example:**
```
MUSIC_ACOUSTID_API_KEY=your_acoustid_key
MUSIC_ACOUSTID_ENABLED=true
```

---

## YouTube

### `YOUTUBE_DATA_API_KEY` (optional)

Google YouTube Data API v3 key. Get one from the [Google Cloud Console](https://console.cloud.google.com/apis/credentials).

**Effect:** Enables richer YouTube metadata retrieval (video titles, descriptions, channel info, duration) before scraping. Without it, the bot still works but relies on yt-dlp for metadata, which can be slower or less detailed.

**Example:**
```
YOUTUBE_DATA_API_KEY=AIza...
```

---

## Local Whisper Settings

### `WHISPER_MODEL` (optional, default: `base`)

Which OpenAI Whisper model to load locally for audio transcription. Only used when `AUDIO_AI_MODEL` is not set (i.e. local transcription mode).

| Value | Size | Speed | Accuracy |
|---|---|---|---|
| `tiny` | 39M | Fastest | Lowest |
| `base` | 74M | Fast | Good (default) |
| `small` | 244M | Medium | Better |
| `medium` | 769M | Slow | High |
| `large` | 1.5G | Slowest | Highest |

**Example:**
```
WHISPER_MODEL=small
```

### `LOCAL_TRANSCRIBE_MAX_MINUTES` (optional, default: `15`)

Maximum audio duration (in minutes) that local Whisper will attempt to transcribe. Files longer than this fall back to Deepgram (if `DEEPGRAM_API_KEY` is set) or fail.

**Effect:** Prevents local Whisper from getting stuck on very long audio files that would take too long or run out of memory.

**Example:**
```
LOCAL_TRANSCRIBE_MAX_MINUTES=30
```

---

## Bot Behavior

### `BOT_PREFIX` (optional, default: `!summarize`)

The command prefix users type in Discord to trigger the bot. Only applies to the Discord bot version.

### `MAX_CONCURRENT_JOBS` (optional, default: `3`)

Maximum number of scraping/analysis jobs that can run simultaneously. Higher values use more CPU/RAM but process requests faster.

### `MESSAGE_CHUNK_SIZE` (optional, default: `1900`)

Maximum characters per Discord message chunk. Discord has a 2000-char limit; this leaves room for formatting. Only applies to the Discord bot version.

### `DOWNLOADS_DIR` (optional, default: `Download Audio File For AI`)

Directory name for temporary downloaded files (audio, video, documents). Created automatically.

### `TEMP_SWEEP_HOURS` (optional, default: `6`)

How often (in hours) to clean up old temporary files from the downloads directory.

### `MAX_FILE_SIZE_MB` (optional, default: `200`)

Maximum allowed file size in megabytes for uploaded or downloaded files. Files larger than this are rejected.

### `REPLY_TO_ALL_SERVER_MESSAGES` (optional, default: `true`)

When enabled, the Discord bot responds to all messages in the server, not just those with the bot prefix. Only applies to the Discord bot version.

---

## Vision Settings

### `ENABLE_LOCAL_VISION` (optional, default: `true`)

Enable local image analysis using BLIP captioning and DETR object detection. These models run on your machine and provide descriptions of images found in scraped content.

### `VISION_CAPTION_MODEL` (optional, default: `Salesforce/blip-image-captioning-base`)

HuggingFace model ID for local image captioning. Only used when `ENABLE_LOCAL_VISION=true`.

### `VISION_OBJECT_MODEL` (optional, default: `facebook/detr-resnet-50`)

HuggingFace model ID for local object detection. Only used when `ENABLE_LOCAL_VISION=true`.

---

## Music Detection Settings

### `ENABLE_MUSIC_DETECTION` (optional, default: `true`)

Master switch for all music detection features (AcoustID, Essentia, MIRFLEX).

### `MUSIC_ANALYSIS_SAMPLE_SECONDS` (optional, default: `90`)

How many seconds of audio to analyze for music detection. Longer samples are more accurate but slower.

### `MUSIC_ACOUSTID_ENABLED` (optional, default: `false`)

Enable AcoustID fingerprinting. Requires `MUSIC_ACOUSTID_API_KEY` and the `fpcalc` binary.

### `MUSIC_ACOUSTID_TIMEOUT_SECONDS` (optional, default: `20`)

Timeout for AcoustID API requests.

### `MUSIC_FPCALC_BINARY` (optional, default: `fpcalc`)

Path to the Chromaprint `fpcalc` binary used for audio fingerprinting. Install via your package manager (e.g. `brew install chromaprint` on macOS).

### `MUSIC_ESSENTIA_ENABLED` (optional, default: `true`)

Enable Essentia-based music analysis (tempo, key, mood detection). Requires the `essentia` Python package.

### `MUSIC_MIRFLEX_ENABLED` (optional, default: `false`)

Enable MIRFLEX music analysis. Experimental. Requires cloning the MIRFLEX repo.

### `MUSIC_MIRFLEX_REPO_PATH` (optional)

Local path to the cloned MIRFLEX repository. Required when `MUSIC_MIRFLEX_ENABLED=true`.

---

## YouTube Auth & Tuning

These settings control how the bot interacts with YouTube. Most users don't need to change these.

### `YOUTUBE_COOKIE_MODE_ENABLED` (optional, default: `false`)

Enable cookie-based YouTube authentication. Helps bypass age-restricted or region-locked videos.

### `YOUTUBE_COOKIES_FROM_BROWSER` (optional)

Browser to extract YouTube cookies from (e.g. `chrome`, `firefox`, `edge`). Used with `YOUTUBE_COOKIE_MODE_ENABLED=true`.

### `YOUTUBE_COOKIES_BROWSER_PROFILE` (optional)

Browser profile name for cookie extraction (e.g. `Default`, `Profile 1`).

### `YOUTUBE_COOKIES_FILE` (optional)

Path to a Netscape-format cookies.txt file as an alternative to browser cookie extraction.

### `YOUTUBE_REQUIRE_BROWSER_PROFILE_FOR_COOKIES` (optional, default: `true`)

Whether to require a browser profile name when using browser-based cookie extraction.

### `YOUTUBE_TRANSCRIPT_API_TIMEOUT_SECONDS` (optional, default: `5`)

Timeout for YouTube transcript API requests.

### `YOUTUBE_YTDLP_TIMEOUT_SECONDS` (optional, default: `10`)

Timeout for yt-dlp operations.

### `YOUTUBE_DOWNSUB_ENABLED` (optional, default: `true`)

Enable DownSub as a fallback subtitle source.

### `YOUTUBE_DOWNSUB_TIMEOUT_SECONDS` (optional, default: `45`)

Timeout for DownSub requests.

### `YOUTUBE_SAVESUBS_ENABLED` (optional, default: `true`)

Enable SaveSubs as a fallback subtitle source.

### `YOUTUBE_SAVESUBS_TIMEOUT_SECONDS` (optional, default: `45`)

Timeout for SaveSubs requests.

### `YOUTUBE_TRANSCRIPT_SITE_HEADLESS` (optional, default: `true`)

Run browser-based subtitle extraction in headless mode.

### `YOUTUBE_TRANSCRIPT_SITE_BROWSER_CHANNEL` (optional, default: `chrome`)

Browser channel for Playwright-based subtitle extraction.

### `YOUTUBE_MIN_REQUEST_INTERVAL_SECONDS` (optional, default: `8`)

Minimum delay between YouTube API requests to avoid rate limiting.

### `YOUTUBE_SLEEP_INTERVAL_SECONDS` (optional, default: `5`)

Base sleep time between YouTube operations.

### `YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS` (optional, default: `15`)

Maximum sleep time between YouTube operations.

### `YOUTUBE_AUTH_GATE_COOLDOWN_MINUTES` (optional, default: `30`)

Cooldown period after hitting a YouTube auth gate for a specific video.

### `YOUTUBE_AUTH_GATE_GLOBAL_THRESHOLD` (optional, default: `3`)

Number of auth gate hits before triggering a global cooldown.

### `YOUTUBE_AUTH_GATE_GLOBAL_COOLDOWN_MINUTES` (optional, default: `180`)

Global cooldown period after hitting too many auth gates.

### `YOUTUBE_RESULT_CACHE_MINUTES` (optional, default: `180`)

How long to cache YouTube scrape results.

### `YOUTUBE_TRANSCRIPT_WINDOW_SECONDS` (optional, default: `150`)

Window size for transcript segment processing.

### `VIDEO_SCAN_BASE_INTERVAL_SECONDS` (optional, default: `3`)

Base interval between video frame scans during video analysis.

### `VIDEO_SCAN_MAX_INTERVAL_SECONDS` (optional, default: `25`)

Maximum interval between video frame scans.

---

## Legacy / Backward Compatibility

These variables are from the original MiniMax-only version. They still work but are superseded by `TEXT_AI_MODEL` + `TEXT_AI_API_KEY`:

| Old Variable | Replaced By |
|---|---|
| `MINIMAX_API_KEY` | `TEXT_AI_API_KEY` (when using a MiniMax model) |
| `MINIMAX_API_URL` | Still needed for MiniMax custom endpoints |
| `MINIMAX_MODEL` | `TEXT_AI_MODEL=minimax-m2.7` (or similar) |
| `MINIMAX_VISION_MODEL` | Vision model is now the same as text model |
| `SUMMARIZER_PROVIDER` | No longer needed (LiteLLM handles routing) |
| `LLM_MODEL` | `TEXT_AI_MODEL` |
| `LLM_VISION_MODEL` | Vision model is now the same as text model |
| `TRANSCRIPTION_MODEL` | `AUDIO_AI_MODEL` |
| `DEEPGRAM_API_KEY` | `AUDIO_AI_API_KEY` (when using a Deepgram model) |
| `DEEPGRAM_MODEL` | `AUDIO_AI_MODEL=deepgram/nova-3` |

If you set `TEXT_AI_MODEL`, the old variables are ignored (except `MINIMAX_API_URL` which is still needed for MiniMax custom endpoints). If you don't set `TEXT_AI_MODEL`, the system falls back to reading the old `MINIMAX_*` variables for backward compatibility.
