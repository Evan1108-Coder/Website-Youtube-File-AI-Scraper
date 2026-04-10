from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

NEW_DOWNLOADS_DIR_NAME = "Download Audio File For AI"
OLD_DOWNLOADS_DIR_NAME = "Download Audios For AI"


@dataclass(slots=True)
class Settings:
    summarizer_provider: str
    minimax_api_key: str
    minimax_api_url: str
    minimax_model: str
    minimax_vision_model: str
    deepgram_api_key: str
    deepgram_model: str
    whisper_model: str
    local_transcribe_max_minutes: int
    max_concurrent_jobs: int
    downloads_dir: Path
    max_file_size_mb: int
    enable_local_vision: bool
    vision_caption_model: str
    vision_object_model: str
    enable_music_detection: bool
    music_analysis_sample_seconds: int
    music_acoustid_enabled: bool
    music_acoustid_api_key: str
    music_acoustid_timeout_seconds: int
    music_fpcalc_binary: str
    music_essentia_enabled: bool
    music_mirflex_enabled: bool
    music_mirflex_repo_path: str
    youtube_cookie_mode_enabled: bool
    youtube_cookies_from_browser: str
    youtube_cookies_browser_profile: str
    youtube_cookies_file: str
    youtube_require_browser_profile_for_cookies: bool
    youtube_data_api_key: str
    youtube_transcript_api_timeout_seconds: int
    youtube_ytdlp_timeout_seconds: int
    youtube_downsub_enabled: bool
    youtube_downsub_timeout_seconds: int
    youtube_savesubs_enabled: bool
    youtube_savesubs_timeout_seconds: int
    youtube_transcript_site_headless: bool
    youtube_transcript_site_browser_channel: str
    youtube_min_request_interval_seconds: int
    youtube_sleep_interval_seconds: int
    youtube_max_sleep_interval_seconds: int
    youtube_auth_gate_cooldown_minutes: int
    youtube_auth_gate_global_threshold: int
    youtube_auth_gate_global_cooldown_minutes: int
    youtube_result_cache_minutes: int
    youtube_transcript_window_seconds: int
    video_scan_base_interval_seconds: int
    video_scan_max_interval_seconds: int


def load_settings() -> Settings:
    load_dotenv()
    downloads_dir = _resolve_downloads_dir()
    return Settings(
        summarizer_provider=os.getenv("SUMMARIZER_PROVIDER", "minimax_http"),
        minimax_api_key=os.getenv("MINIMAX_API_KEY", ""),
        minimax_api_url=os.getenv("MINIMAX_API_URL", ""),
        minimax_model=_normalize_minimax_model(os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")),
        minimax_vision_model=_normalize_minimax_model(os.getenv("MINIMAX_VISION_MODEL", "MiniMax-Text-01")),
        deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", ""),
        deepgram_model=os.getenv("DEEPGRAM_MODEL", "nova-3"),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        local_transcribe_max_minutes=int(os.getenv("LOCAL_TRANSCRIBE_MAX_MINUTES", "15")),
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "3")),
        downloads_dir=downloads_dir,
        max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "200")),
        enable_local_vision=_env_bool("ENABLE_LOCAL_VISION", True),
        vision_caption_model=os.getenv(
            "VISION_CAPTION_MODEL",
            "Salesforce/blip-image-captioning-base",
        ),
        vision_object_model=os.getenv(
            "VISION_OBJECT_MODEL",
            "facebook/detr-resnet-50",
        ),
        enable_music_detection=_env_bool("ENABLE_MUSIC_DETECTION", True),
        music_analysis_sample_seconds=int(os.getenv("MUSIC_ANALYSIS_SAMPLE_SECONDS", "90")),
        music_acoustid_enabled=_env_bool("MUSIC_ACOUSTID_ENABLED", False),
        music_acoustid_api_key=os.getenv("MUSIC_ACOUSTID_API_KEY", "").strip(),
        music_acoustid_timeout_seconds=int(os.getenv("MUSIC_ACOUSTID_TIMEOUT_SECONDS", "20")),
        music_fpcalc_binary=os.getenv("MUSIC_FPCALC_BINARY", "fpcalc").strip() or "fpcalc",
        music_essentia_enabled=_env_bool("MUSIC_ESSENTIA_ENABLED", True),
        music_mirflex_enabled=_env_bool("MUSIC_MIRFLEX_ENABLED", False),
        music_mirflex_repo_path=os.getenv("MUSIC_MIRFLEX_REPO_PATH", "").strip(),
        youtube_cookie_mode_enabled=_env_bool("YOUTUBE_COOKIE_MODE_ENABLED", False),
        youtube_cookies_from_browser=os.getenv("YOUTUBE_COOKIES_FROM_BROWSER", "").strip(),
        youtube_cookies_browser_profile=os.getenv("YOUTUBE_COOKIES_BROWSER_PROFILE", "").strip(),
        youtube_cookies_file=os.getenv("YOUTUBE_COOKIES_FILE", "").strip(),
        youtube_require_browser_profile_for_cookies=_env_bool(
            "YOUTUBE_REQUIRE_BROWSER_PROFILE_FOR_COOKIES",
            True,
        ),
        youtube_data_api_key=os.getenv("YOUTUBE_DATA_API_KEY", "").strip(),
        youtube_transcript_api_timeout_seconds=int(
            os.getenv("YOUTUBE_TRANSCRIPT_API_TIMEOUT_SECONDS", "5")
        ),
        youtube_ytdlp_timeout_seconds=int(os.getenv("YOUTUBE_YTDLP_TIMEOUT_SECONDS", "10")),
        youtube_downsub_enabled=_env_bool("YOUTUBE_DOWNSUB_ENABLED", True),
        youtube_downsub_timeout_seconds=int(os.getenv("YOUTUBE_DOWNSUB_TIMEOUT_SECONDS", "45")),
        youtube_savesubs_enabled=_env_bool("YOUTUBE_SAVESUBS_ENABLED", True),
        youtube_savesubs_timeout_seconds=int(os.getenv("YOUTUBE_SAVESUBS_TIMEOUT_SECONDS", "45")),
        youtube_transcript_site_headless=_env_bool("YOUTUBE_TRANSCRIPT_SITE_HEADLESS", True),
        youtube_transcript_site_browser_channel=os.getenv("YOUTUBE_TRANSCRIPT_SITE_BROWSER_CHANNEL", "chrome").strip(),
        youtube_min_request_interval_seconds=int(os.getenv("YOUTUBE_MIN_REQUEST_INTERVAL_SECONDS", "8")),
        youtube_sleep_interval_seconds=int(os.getenv("YOUTUBE_SLEEP_INTERVAL_SECONDS", "5")),
        youtube_max_sleep_interval_seconds=int(os.getenv("YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS", "15")),
        youtube_auth_gate_cooldown_minutes=int(os.getenv("YOUTUBE_AUTH_GATE_COOLDOWN_MINUTES", "30")),
        youtube_auth_gate_global_threshold=int(os.getenv("YOUTUBE_AUTH_GATE_GLOBAL_THRESHOLD", "3")),
        youtube_auth_gate_global_cooldown_minutes=int(
            os.getenv("YOUTUBE_AUTH_GATE_GLOBAL_COOLDOWN_MINUTES", "180")
        ),
        youtube_result_cache_minutes=int(os.getenv("YOUTUBE_RESULT_CACHE_MINUTES", "180")),
        youtube_transcript_window_seconds=int(os.getenv("YOUTUBE_TRANSCRIPT_WINDOW_SECONDS", "150")),
        video_scan_base_interval_seconds=int(os.getenv("VIDEO_SCAN_BASE_INTERVAL_SECONDS", "3")),
        video_scan_max_interval_seconds=int(os.getenv("VIDEO_SCAN_MAX_INTERVAL_SECONDS", "25")),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_minimax_model(raw: str) -> str:
    value = raw.strip() or "MiniMax-M2.5"
    normalized = value.lower()
    aliases = {
        "m2.7": "MiniMax-M2.7",
        "minimax-m2.7": "MiniMax-M2.7",
        "m2.7-highspeed": "MiniMax-M2.7-highspeed",
        "minimax-m2.7-highspeed": "MiniMax-M2.7-highspeed",
        "m2.5": "MiniMax-M2.5",
        "minimax-m2.5": "MiniMax-M2.5",
        "m2.5-highspeed": "MiniMax-M2.5-highspeed",
        "minimax-m2.5-highspeed": "MiniMax-M2.5-highspeed",
        "m2.1": "MiniMax-M2.1",
        "minimax-m2.1": "MiniMax-M2.1",
        "m2.1-highspeed": "MiniMax-M2.1-highspeed",
        "minimax-m2.1-highspeed": "MiniMax-M2.1-highspeed",
        "m2": "MiniMax-M2",
        "minimax-m2": "MiniMax-M2",
        "text-01": "MiniMax-Text-01",
        "minimax-text-01": "MiniMax-Text-01",
    }
    return aliases.get(normalized, value)


def _resolve_downloads_dir() -> Path:
    raw = os.getenv("DOWNLOADS_DIR", "").strip()
    if not raw or raw in {OLD_DOWNLOADS_DIR_NAME, "Download Audio/File For AI"}:
        raw = NEW_DOWNLOADS_DIR_NAME
    return Path(raw).resolve()
