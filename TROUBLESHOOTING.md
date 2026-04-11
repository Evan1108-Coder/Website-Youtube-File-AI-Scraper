# Troubleshooting Guide

This guide covers common problems you might run into while setting up or running the website version of the AI Website Scraper + Summarizer.

If something is not covered here, check the terminal output for specific error messages and compare them against the sections below.

---

## Table of Contents

- [Installation Issues](#installation-issues)
- [Python and Virtual Environment Issues](#python-and-virtual-environment-issues)
- [Dependency and Build Issues](#dependency-and-build-issues)
- [Environment Configuration Issues](#environment-configuration-issues)
- [AI Model and API Key Issues](#ai-model-and-api-key-issues)
- [LiteLLM Provider Routing Issues](#litellm-provider-routing-issues)
- [Web UI Issues](#web-ui-issues)
- [Website Scraping Issues](#website-scraping-issues)
- [YouTube Issues](#youtube-issues)
- [Audio Transcription Issues](#audio-transcription-issues)
- [Video Analysis Issues](#video-analysis-issues)
- [Image Analysis Issues](#image-analysis-issues)
- [Music Detection Issues](#music-detection-issues)
- [File Upload and Parsing Issues](#file-upload-and-parsing-issues)
- [Performance Issues](#performance-issues)
- [Network and SSL Issues](#network-and-ssl-issues)

---

## Installation Issues

### Homebrew is not installed

**Symptom:** `brew: command not found`

**Fix:** Install Homebrew from https://brew.sh, then restart your terminal.

---

### FFmpeg is not installed

**Symptom:** Errors mentioning `ffmpeg` or `ffprobe` not found. Audio extraction, video frame extraction, and media probing will fail.

**Fix:**

```bash
brew install ffmpeg
```

Verify with:

```bash
ffmpeg -version
ffprobe -version
```

---

### Tesseract is not installed

**Symptom:** OCR fails on images. Error message mentions `tesseract` not found.

**Fix:**

```bash
brew install tesseract
```

Verify with:

```bash
tesseract --version
```

---

### Playwright Chromium is not installed

**Symptom:** DownSub and SaveSubs YouTube fallbacks fail. Errors mention missing browser or Chromium.

**Fix:**

```bash
playwright install chromium
```

Make sure you run this inside your activated virtual environment.

---

### `fpcalc` is not installed (AcoustID)

**Symptom:** AcoustID fingerprinting fails. Error mentions `fpcalc` not found.

**Fix:**

```bash
brew install chromaprint
```

Verify with:

```bash
fpcalc -version
```

This is only needed if `MUSIC_ACOUSTID_ENABLED=true`.

---

## Python and Virtual Environment Issues

### Wrong Python version

**Symptom:** Import errors, syntax errors, or dependency build failures. This project is designed for Python 3.11.

**Fix:**

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### Virtual environment not activated

**Symptom:** `ModuleNotFoundError` for packages like `fastapi`, `litellm`, `discord`, etc. even though you installed them.

**Fix:** Make sure you activate the venv before running:

```bash
source .venv/bin/activate
```

Your terminal prompt should show `(.venv)` at the start.

---

### `ModuleNotFoundError: No module named 'ai_scraper_bot'`

**Symptom:** Running the app fails because Python cannot find the project package.

**Fix:** You need to set `PYTHONPATH=src` when running:

```bash
PYTHONPATH=src python -m ai_scraper_bot.webapp
```

This is the correct run command. Do not try to run `python src/ai_scraper_bot/webapp.py` directly.

---

## Dependency and Build Issues

### NumPy version conflict

**Symptom:** Errors mentioning NumPy incompatibility, especially with Whisper or torch. Messages like `numpy.core.multiarray failed to import` or `A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x`.

**Fix:** This project requires `numpy<2`:

```bash
pip install "numpy<2"
pip install -r requirements.txt
```

---

### `llvmlite` build error

**Symptom:** `pip install` fails trying to compile `llvmlite` from source. Long C/C++ compiler error output.

**Fix:**

- Do not use `--force-reinstall` — that forces source builds.
- Make sure you are on Python 3.11 (not 3.13 or 3.14 where binary wheels may not exist yet).
- Try reinstalling normally:

```bash
pip install -r requirements.txt
```

If the error persists, try installing `llvmlite` separately first:

```bash
pip install llvmlite==0.45.1
```

---

### `numba` build error

**Symptom:** Similar to `llvmlite` — fails to compile. `numba` depends on `llvmlite`.

**Fix:** Same as above. Make sure you are on Python 3.11 and use the pinned versions in `requirements.txt`.

---

### Rust compiler not found

**Symptom:** `pip install` fails with errors about Rust/cargo not being available. This happens when building some Whisper dependencies from source.

**Fix:**

```bash
brew install rust
```

Then retry `pip install -r requirements.txt`.

---

### `torch` installation fails or takes very long

**Symptom:** PyTorch download is slow or fails. The project pins `torch==2.2.2`.

**Fix:**

- Make sure you have a stable internet connection.
- If on Apple Silicon, the correct wheel should install automatically for Python 3.11.
- Do not upgrade torch beyond 2.2.2 unless you verify compatibility with Whisper and the other dependencies.

---

### `essentia` fails to install

**Symptom:** `pip install essentia` fails with build errors.

**Fix:**

- Essentia requires Python 3.11 or compatible. It may not have wheels for Python 3.13+.
- If it still fails, you can disable Essentia in `.env`:

```env
MUSIC_ESSENTIA_ENABLED=false
```

The rest of the app will still work; you just lose local music feature analysis.

---

## Environment Configuration Issues

### `.env` file does not exist

**Symptom:** The app starts but nothing works. No API key is loaded. The health endpoint shows `"llm_configured": false`.

**Fix:**

```bash
cp .env.example .env
```

Then edit `.env` and fill in your values.

---

### `.env` file has extra spaces or quotes

**Symptom:** API key is set but the provider returns authentication errors.

**Fix:** Make sure your `.env` values do not have quotes or trailing spaces:

```env
# WRONG:
TEXT_AI_API_KEY="sk-proj-abc123"
TEXT_AI_API_KEY=sk-proj-abc123

# CORRECT:
TEXT_AI_API_KEY=sk-proj-abc123
```

The `python-dotenv` library handles most cases, but extra quotes can sometimes cause issues with certain API providers.

---

### `TEXT_AI_MODEL` is empty

**Symptom:** Health endpoint shows `"llm_configured": false`. Summaries fail. The terminal shows a warning: `No AI model configured`.

**Fix:** Set `TEXT_AI_MODEL` in `.env`:

```env
TEXT_AI_MODEL=gpt-4o
TEXT_AI_API_KEY=sk-proj-your_key_here
```

See [ENVREADME.md](ENVREADME.md) for the full list of supported models.

---

### `TEXT_AI_API_KEY` is empty or wrong

**Symptom:** Summaries fail with authentication errors. LiteLLM raises `AuthenticationError` or `401 Unauthorized`.

**Fix:**

- Make sure the key matches the provider for your chosen model.
- An OpenAI key will not work with an Anthropic model, and vice versa.
- Double-check the key has not expired or been revoked.

---

### Using the wrong API key for the model

**Symptom:** `AuthenticationError`, `Invalid API Key`, or `401` errors from the AI provider.

**Fix:** The key must match the provider:

| Model prefix | Provider | Key format |
|---|---|---|
| `gpt-*` | OpenAI | `sk-proj-...` or `sk-...` |
| `claude-*` | Anthropic | `sk-ant-...` |
| `gemini-*` | Google | Google API key |
| `llama-*` | Together AI | Together AI key |
| `minimax-*` | MiniMax | MiniMax key |

---

## AI Model and API Key Issues

### `BadRequestError` or `Model not found`

**Symptom:** LiteLLM returns a `BadRequestError` saying the model is not found or not supported.

**Fix:**

- Check that your `TEXT_AI_MODEL` value exactly matches one of the supported model names (see the table in README.md).
- Model names are case-insensitive for the built-in aliases, but custom LiteLLM model strings must be exact.
- If using a custom model string with a provider prefix (e.g. `openai/gpt-4o`), make sure the format is correct.

---

### Rate limit or quota exceeded

**Symptom:** `RateLimitError`, `429 Too Many Requests`, or messages about quota exceeded.

**Fix:**

- Wait and try again later.
- Check your provider dashboard for current usage and limits.
- Some free tiers (like GitHub Models) have strict token/request limits.
- Consider switching to a model with higher limits.

---

### Model works but responses are cut off

**Symptom:** AI responses end abruptly or seem incomplete.

**Fix:**

- Some models have lower output token limits. Try a different model.
- If using a free tier endpoint, check if there are token limits per request.
- This is a provider limitation, not a code issue.

---

### MiniMax model fails

**Symptom:** MiniMax requests fail with connection errors or 404.

**Fix:** MiniMax models require an additional `MINIMAX_API_URL` in `.env`:

```env
TEXT_AI_MODEL=minimax-m2.7
TEXT_AI_API_KEY=your_minimax_key
MINIMAX_API_URL=https://your_minimax_chat_endpoint
```

The URL must be the base chat endpoint provided by MiniMax. The code strips `/chat/completions` and similar suffixes automatically, but the base URL must be correct.

---

### Legacy `MINIMAX_*` variables not working after upgrade

**Symptom:** You upgraded from the original MiniMax-only version and the bot no longer connects to MiniMax.

**Fix:** The legacy variables (`MINIMAX_API_KEY`, `MINIMAX_MODEL`, `MINIMAX_VISION_MODEL`) still work as a fallback, but only if `TEXT_AI_MODEL` is empty. If you set `TEXT_AI_MODEL`, the legacy variables are ignored (except `MINIMAX_API_URL` which is still needed for MiniMax routing).

Recommended: switch to the new format:

```env
TEXT_AI_MODEL=minimax-m2.7
TEXT_AI_API_KEY=your_minimax_key
MINIMAX_API_URL=https://your_minimax_endpoint
```

---

## LiteLLM Provider Routing Issues

### `LLM Provider NOT provided`

**Symptom:** LiteLLM raises `BadRequestError: LLM Provider NOT provided`.

**Fix:** This means LiteLLM cannot determine which provider to use from the model string. This typically happens when:

- You pass a model name that has no recognized prefix and is not in the built-in alias list.
- You are using a custom endpoint (like GitHub Models or Azure) with a non-standard model name.

For custom endpoints, prefix the model with `openai/`:

```env
TEXT_AI_MODEL=openai/Meta-Llama-3.1-8B-Instruct
```

Or use the `OPENAI_API_BASE` environment variable to point LiteLLM at your custom endpoint.

---

### Provider-specific API key not being picked up

**Symptom:** You set `TEXT_AI_API_KEY` but the provider complains about a missing key.

**Fix:** The system auto-maps `TEXT_AI_API_KEY` to the correct provider env var based on the model prefix:

- `gpt-*` → sets `OPENAI_API_KEY`
- `claude-*` → sets `ANTHROPIC_API_KEY`
- `gemini-*` → sets `GEMINI_API_KEY`
- `llama-*` → sets `TOGETHER_AI_API_KEY`

If auto-detection is not working for your setup, you can also set the provider-specific key directly in `.env`:

```env
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
TOGETHER_AI_API_KEY=...
```

---

### Using a custom OpenAI-compatible endpoint

**Symptom:** You want to use a custom endpoint (Azure, GitHub Models, local LLM server, etc.) but requests go to the default OpenAI endpoint.

**Fix:** Set `OPENAI_API_BASE` in your `.env`:

```env
OPENAI_API_BASE=https://models.inference.ai.azure.com
TEXT_AI_MODEL=gpt-4o-mini
TEXT_AI_API_KEY=your_token
```

For non-OpenAI models on a custom endpoint, prefix with `openai/`:

```env
TEXT_AI_MODEL=openai/Meta-Llama-3.1-8B-Instruct
```

---

## Web UI Issues

### Website does not load at all

**Symptom:** Browser shows "connection refused" or blank page at `http://127.0.0.1:8000`.

**Fix:**

1. Make sure the server is actually running. You should see startup logs in the terminal.
2. Check if port 8000 is already in use:

```bash
lsof -i :8000
```

3. If the port is busy, change it in `.env`:

```env
WEBAPP_PORT=8001
```

4. Make sure you are using `http://`, not `https://`.

---

### Website loads but shows no chats

**Symptom:** The sidebar is empty. No chats appear.

**Fix:** This is normal on first launch. Click the "New Chat" button to create your first chat.

---

### Website loads but AI responses fail

**Symptom:** You can type messages but the AI never responds, or responses show errors.

**Fix:**

1. Check the health endpoint: `http://127.0.0.1:8000/api/health`
2. If `"llm_configured": false`, your `.env` is not set up correctly.
3. Check the terminal for error messages from LiteLLM.
4. Try a simple test message first (like "Hello") to isolate the issue.

---

### `Address already in use` error on startup

**Symptom:** The server fails to start with `OSError: [Errno 48] Address already in use`.

**Fix:**

1. Another process is using port 8000. Find and stop it:

```bash
lsof -i :8000
kill <PID>
```

2. Or change the port in `.env`:

```env
WEBAPP_PORT=8001
```

---

### Chat history is lost after restart

**Symptom:** All chats disappear when the server restarts.

**Fix:** Chat history is stored in an SQLite database at `WEBAPP_DB_PATH` (default: `./.webapp/webapp.sqlite`).

- Make sure the `.webapp` directory exists and is writable.
- If you delete or move the database file, history is lost.
- The database path is relative to where you run the command from.

---

### Maximum 10 chats reached

**Symptom:** Cannot create new chats. Error message about chat limit.

**Fix:** The app has a hardcoded limit of 10 chats. Delete old chats you no longer need using the trash icon in the sidebar.

---

### File upload fails with "file too large"

**Symptom:** Uploading a file returns an error about file size.

**Fix:** The default limit is 200 MB. You can change it in `.env`:

```env
MAX_FILE_SIZE_MB=500
```

---

### Static files (CSS/JS) return 404

**Symptom:** The website loads but looks broken — no styling, no interactivity.

**Fix:** This usually means the static file directory is not found. Make sure you are running from the project root directory:

```bash
cd /path/to/Website-Youtube-File-AI-Scraper
PYTHONPATH=src python -m ai_scraper_bot.webapp
```

---

## Website Scraping Issues

### Website extraction returns empty or very short content

**Symptom:** Summarizing a website URL returns very little content.

**Fix:**

- Some websites block automated scrapers or use heavy JavaScript rendering.
- The scraper uses `trafilatura` and `BeautifulSoup` for extraction.
- JavaScript-only pages (SPAs) may not extract well.
- Try a different URL to confirm the scraper is working in general.

---

### Website extraction times out

**Symptom:** The request hangs for a long time and then fails.

**Fix:** Website extraction has a 75-second timeout. If the target site is slow or unresponsive, this can trigger.

- Check that the URL is reachable from your machine.
- Check your network/proxy/VPN configuration.

---

## YouTube Issues

### YouTube transcript extraction fails completely

**Symptom:** All YouTube transcript methods fail. The bot falls back to metadata only.

**Fix:** The system tries 5 methods in order:

1. `youtube-transcript-api`
2. `yt-dlp` subtitle extraction
3. `DownSub + Playwright`
4. `SaveSubs + Playwright`
5. Metadata-only fallback

If all transcript methods fail:

- YouTube may be actively blocking requests from your IP.
- Try enabling cookie mode if you have a YouTube account:

```env
YOUTUBE_COOKIE_MODE_ENABLED=true
YOUTUBE_COOKIES_FROM_BROWSER=chrome
```

- Make sure Playwright Chromium is installed: `playwright install chromium`
- Check if `yt-dlp` is up to date: `pip install --upgrade yt-dlp`

---

### `youtube-transcript-api` returns "No transcript found"

**Symptom:** The first transcript method fails. The video may not have captions.

**Fix:**

- Not all YouTube videos have transcripts/captions.
- The system will automatically try the next method.
- If the video has auto-generated captions, they may only be available through `yt-dlp`.

---

### DownSub or SaveSubs fails

**Symptom:** Playwright-based transcript fallbacks fail with browser errors.

**Fix:**

1. Make sure Playwright Chromium is installed:

```bash
playwright install chromium
```

2. Make sure the headless setting is correct:

```env
YOUTUBE_TRANSCRIPT_SITE_HEADLESS=true
```

3. These services depend on third-party websites (downsub.com, savesubs.com). If those sites are down or have changed their layout, the fallback will fail.

---

### `yt-dlp` fails with "Sign in to confirm your age" or similar

**Symptom:** `yt-dlp` returns an error about age verification or sign-in requirements.

**Fix:** Enable cookie mode to pass your browser session to `yt-dlp`:

```env
YOUTUBE_COOKIE_MODE_ENABLED=true
YOUTUBE_COOKIES_FROM_BROWSER=chrome
```

Make sure Chrome is signed into a YouTube account.

---

### `yt-dlp` complains about JavaScript runtime

**Symptom:** `yt-dlp` warns about missing JavaScript interpreter support.

**Fix:**

```bash
brew install node
```

or

```bash
brew install deno
```

---

### YouTube rate limiting

**Symptom:** YouTube works for a few requests then stops. Auth gate messages appear in the log.

**Fix:** The system has built-in rate limiting and cooldown settings:

```env
YOUTUBE_MIN_REQUEST_INTERVAL_SECONDS=8
YOUTUBE_AUTH_GATE_COOLDOWN_MINUTES=30
YOUTUBE_AUTH_GATE_GLOBAL_THRESHOLD=3
YOUTUBE_AUTH_GATE_GLOBAL_COOLDOWN_MINUTES=180
```

If you are hitting rate limits frequently:

- Increase the cooldown values.
- Add a YouTube Data API key for metadata (reduces direct scraping).
- Space out your requests.

---

## Audio Transcription Issues

### Local Whisper transcription is very slow

**Symptom:** Transcribing audio takes minutes, especially for longer files.

**Fix:**

- Lower the local transcription threshold so long files go to cloud instead:

```env
LOCAL_TRANSCRIBE_MAX_MINUTES=5
```

- Use a smaller Whisper model:

```env
WHISPER_MODEL=tiny
```

- Or configure cloud transcription:

```env
AUDIO_AI_MODEL=whisper-1
AUDIO_AI_API_KEY=sk-proj-your_openai_key
```

---

### Whisper fails with NumPy errors

**Symptom:** `numpy.core.multiarray failed to import` or similar NumPy-related crashes during transcription.

**Fix:** Install the correct NumPy version:

```bash
pip install "numpy<2"
```

---

### Cloud transcription fails with "No API key"

**Symptom:** `AUDIO_AI_MODEL` is set but transcription fails because no key is found.

**Fix:**

- Set `AUDIO_AI_API_KEY` in `.env`.
- If your audio model uses the same provider as your text model, `TEXT_AI_API_KEY` is reused automatically.
- If they are different providers, you must set `AUDIO_AI_API_KEY` explicitly.

---

### Deepgram transcription fails

**Symptom:** Errors mentioning Deepgram API issues.

**Fix:**

- Verify your Deepgram API key is valid.
- Check that you set the model correctly:

```env
AUDIO_AI_MODEL=deepgram/nova-3
AUDIO_AI_API_KEY=your_deepgram_key
```

- You can also set `DEEPGRAM_API_KEY` directly if auto-detection does not work.

---

### Audio extraction fails for video files

**Symptom:** "No audio stream" or `ffmpeg` errors when processing video files.

**Fix:**

- Make sure `ffmpeg` is installed.
- Some video files genuinely have no audio track. In that case, transcript-based analysis will not run, but visual analysis can still proceed.
- Check the video file is not corrupted: `ffprobe your_video.mp4`

---

## Video Analysis Issues

### Video frame analysis returns nothing

**Symptom:** Video is uploaded but no visual analysis is produced.

**Fix:**

- Make sure `ENABLE_LOCAL_VISION=true` in `.env`.
- Make sure `ffmpeg` is installed (needed for frame extraction).
- Check that your AI model supports vision/image inputs. Not all models handle multimodal content.

---

### Video analysis is very slow

**Symptom:** Processing a video takes a very long time.

**Fix:**

- Video analysis extracts and describes individual frames, which requires multiple AI API calls.
- Adjust the scan interval to reduce the number of frames:

```env
VIDEO_SCAN_BASE_INTERVAL_SECONDS=5
VIDEO_SCAN_MAX_INTERVAL_SECONDS=30
```

- Higher values = fewer frames = faster but less detailed.

---

## Image Analysis Issues

### Image descriptions are empty or generic

**Symptom:** Image analysis returns very basic or no descriptions.

**Fix:**

- Make sure `ENABLE_LOCAL_VISION=true`.
- The active visual description engine is your configured `TEXT_AI_MODEL`. Make sure your model supports vision.
- Models that support vision: `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4-6`, `claude-opus-4-6`, `gemini-3-flash`, `gemini-3.1-pro`.
- Some cheaper/smaller models may not handle images well.

---

### AVIF images fail to load

**Symptom:** `.avif` files cause errors during image processing.

**Fix:**

- The project includes `pillow-avif-plugin` for AVIF support.
- If that fails, the code falls back to `ffmpeg` for AVIF decoding.
- Make sure both `Pillow` and `ffmpeg` are installed.

---

### OCR returns garbage or nothing

**Symptom:** Text extraction from images produces meaningless output.

**Fix:**

- Make sure `tesseract` is installed.
- OCR quality depends on image clarity, contrast, text size, and language.
- Very stylized text, handwriting, or low-resolution images will produce poor OCR results.
- This is a Tesseract limitation, not a code issue.

---

## Music Detection Issues

### Essentia analysis returns nothing

**Symptom:** Music analysis runs but produces no BPM, key, or loudness data.

**Fix:**

- Make sure `MUSIC_ESSENTIA_ENABLED=true`.
- Make sure `essentia` is installed: `pip list | grep essentia`
- The audio file must actually contain music-like content.
- Very short clips may not produce reliable analysis.

---

### AcoustID returns no matches

**Symptom:** AcoustID fingerprinting completes but finds no song match.

**Fix:**

- AcoustID only matches songs that are in its database. Not all songs are indexed.
- Make sure the audio clip is at least 10-20 seconds long.
- Check that your API key is valid at https://acoustid.org/my-applications.

---

### AcoustID fails with "fpcalc not found"

**Symptom:** Error about `fpcalc` binary not being available.

**Fix:**

```bash
brew install chromaprint
```

Or point to a custom path:

```env
MUSIC_FPCALC_BINARY=/usr/local/bin/fpcalc
```

---

### MIRFLEX is enabled but not working

**Symptom:** MIRFLEX is set to `true` but produces no output.

**Fix:**

- MIRFLEX is treated as an optional repo hook. Setting the path is necessary but may not be sufficient.
- The MIRFLEX repo needs its own setup, model files, and inference configuration.
- The rest of the music pipeline will still continue even if MIRFLEX fails.
- If you do not need MIRFLEX:

```env
MUSIC_MIRFLEX_ENABLED=false
```

---

## File Upload and Parsing Issues

### Unsupported file type error

**Symptom:** Uploading a file returns "unsupported file type".

**Fix:** The supported file types are:

- Text: `.txt`, `.md`, `.csv`, `.json`, `.html`, `.xml`
- Documents: `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.rtf`
- Images: `.png`, `.jpg`, `.jpeg`, `.avif`
- Audio: `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`
- Video: `.mp4`, `.mov`

Other file types are not supported. Rename workarounds (like `.txt` for an unsupported format) may produce garbage output.

---

### PDF parsing returns empty content

**Symptom:** A PDF file uploads but the extracted text is empty or very short.

**Fix:**

- Some PDFs are image-only (scanned documents). The text extraction libraries (`pypdf`, `pdfplumber`) cannot extract text from images inside PDFs.
- For scanned PDFs, the content would need OCR processing, which is not currently applied to PDFs.

---

### DOCX/PPTX/XLSX parsing fails

**Symptom:** Office document parsing returns an error.

**Fix:**

- Make sure the relevant libraries are installed: `python-docx`, `python-pptx`, `openpyxl`.
- The file may be corrupted or password-protected.
- Password-protected documents are not supported.

---

## Performance Issues

### The app uses too much memory

**Symptom:** High RAM usage, especially during transcription or vision model loading.

**Fix:**

- Local Whisper and torch models consume significant RAM (1-4 GB or more).
- Reduce memory by using smaller models:

```env
WHISPER_MODEL=tiny
```

- Reduce concurrent processing:

```env
MAX_CONCURRENT_JOBS=1
```

- Consider using cloud transcription instead of local Whisper.

---

### The app is very slow on first request

**Symptom:** The first audio/image/video request takes much longer than subsequent ones.

**Fix:** This is normal. Models like Whisper, BLIP, and DETR are loaded on first use and cached in memory. Subsequent requests will be faster.

---

## Network and SSL Issues

### SSL certificate verification fails

**Symptom:** `ssl.SSLCertVerificationError: certificate verify failed` when making requests.

**Fix:** This is a common macOS Python issue. Install the SSL certificates:

```bash
/Applications/Python\ 3.11/Install\ Certificates.command
```

Or if installed via Homebrew:

```bash
pip install certifi
```

---

### Cannot reach AI provider API

**Symptom:** Connection timeout or connection refused when calling the AI API.

**Fix:**

- Check your internet connection.
- If behind a VPN or proxy, make sure it allows connections to your AI provider.
- Check if the provider is experiencing an outage (check their status page).
- For corporate networks, you may need to configure proxy settings.

---

### `OPENAI_API_BASE` is set but requests still go to OpenAI

**Symptom:** You set a custom API base but requests are not being routed there.

**Fix:**

- Make sure the variable is set in `.env`, not just exported in the shell.
- Restart the server after changing `.env`.
- Verify with the health endpoint: `http://127.0.0.1:8000/api/health`

---

## Still Stuck?

If none of the above sections solve your problem:

1. Check the terminal output for the exact error message.
2. Look for the error in the LiteLLM documentation: https://docs.litellm.ai/
3. Make sure all system tools are installed: `ffmpeg`, `ffprobe`, `tesseract`, Playwright Chromium.
4. Try a fresh virtual environment:

```bash
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

5. Verify your `.env` file matches `.env.example` in structure.

For a complete reference of every environment variable, see [ENVREADME.md](ENVREADME.md).
