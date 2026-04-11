from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import tempfile
from pathlib import Path

import httpx
import litellm
import numpy as np

from ai_scraper_bot.config import Settings


class TranscriptionError(RuntimeError):
    pass


class TranscriptionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._whisper_model = None
        self._whisper_module = None

    async def transcribe_media(self, media_path: Path, duration_minutes: float | None = None) -> str:
        model = self.settings.transcription_model
        if model and model != "local":
            return await self._transcribe_with_litellm(media_path, model)
        if duration_minutes is not None and duration_minutes > self.settings.local_transcribe_max_minutes:
            if self.settings.deepgram_api_key:
                return await self._transcribe_with_deepgram(media_path)
        return await self._transcribe_with_whisper(media_path)

    async def transcribe_video_media(self, media_path: Path, duration_minutes: float | None = None) -> str:
        extracted_audio = await self._extract_audio_track(media_path)
        try:
            return await self.transcribe_media(extracted_audio, duration_minutes)
        finally:
            await asyncio.to_thread(extracted_audio.unlink, True)

    async def probe_duration_minutes(self, media_path: Path) -> float | None:
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(media_path),
        ]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None

        try:
            data = json.loads(completed.stdout)
            seconds = float(data["format"]["duration"])
            return seconds / 60
        except (KeyError, ValueError, json.JSONDecodeError):
            return None

    async def _transcribe_with_whisper(self, media_path: Path) -> str:
        model = await self._get_whisper_model()
        result = await asyncio.to_thread(model.transcribe, str(media_path), fp16=False)
        text = result.get("text", "").strip()
        if not text:
            raise TranscriptionError("Whisper did not return any transcript text.")
        return text

    async def _get_whisper_model(self):
        if self._whisper_model is None:
            whisper_module = await self._get_whisper_module()
            self._whisper_model = await asyncio.to_thread(
                whisper_module.load_model, self.settings.whisper_model
            )
        return self._whisper_model

    async def _get_whisper_module(self):
        if self._whisper_module is None:
            numpy_version = tuple(int(part) for part in np.__version__.split(".")[:2] if part.isdigit())
            if numpy_version and numpy_version[0] >= 2:
                raise TranscriptionError(
                    "Local Whisper is currently blocked by a NumPy compatibility issue: this environment has NumPy "
                    f"{np.__version__}, but the pinned torch/whisper stack expects `numpy<2`. "
                    "Fix it inside the active virtual environment with: `pip install \"numpy<2\" --force-reinstall` "
                    "and then reinstall the project requirements."
                )
            try:
                self._whisper_module = await asyncio.to_thread(importlib.import_module, "whisper")
            except Exception as exc:
                raise TranscriptionError(
                    "The bot could not import Whisper locally. This is often caused by a broken torch/NumPy install. "
                    "Reinstall the project requirements after pinning `numpy<2`."
                ) from exc
        return self._whisper_module

    async def _extract_audio_track(self, media_path: Path) -> Path:
        has_audio = await self._media_has_audio_stream(media_path)
        if has_audio is False:
            raise TranscriptionError(
                "This video file does not contain an audio stream, so there was nothing to transcribe."
            )

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False,
            dir=str(media_path.parent),
        ) as handle:
            output_path = Path(handle.name)

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-map",
            "a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(output_path),
            "-y",
        ]
        try:
            await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            output_path.unlink(missing_ok=True)
            raise TranscriptionError("ffmpeg is not available for extracting video audio.") from exc
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            stderr = exc.stderr.strip()
            if _looks_like_missing_audio_stream(stderr):
                raise TranscriptionError(
                    "This video file does not contain an audio stream, so there was nothing to transcribe."
                ) from exc
            raise TranscriptionError(
                f"ffmpeg could not extract an audio track from this video: {_short_ffmpeg_reason(stderr) or exc}"
            ) from exc

        if not output_path.exists() or output_path.stat().st_size <= 0:
            output_path.unlink(missing_ok=True)
            raise TranscriptionError("ffmpeg finished, but no usable audio track was produced from the video.")
        return output_path

    async def _media_has_audio_stream(self, media_path: Path) -> bool | None:
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(media_path),
        ]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        try:
            data = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return None
        streams = data.get("streams")
        if not isinstance(streams, list):
            return None
        return bool(streams)

    async def _transcribe_with_litellm(self, media_path: Path, model: str) -> str:
        try:
            response = await litellm.atranscription(
                model=model,
                file=media_path,
                timeout=300.0,
            )
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed ({model}): {exc}") from exc
        text = response.text.strip() if hasattr(response, "text") else ""
        if not text:
            raise TranscriptionError(f"Transcription returned no text ({model}).")
        return text

    async def _transcribe_with_deepgram(self, media_path: Path) -> str:
        if not self.settings.deepgram_api_key:
            raise TranscriptionError("Deepgram is not configured.")

        headers = {
            "Authorization": f"Token {self.settings.deepgram_api_key}",
            "Content-Type": "application/octet-stream",
        }
        params = {
            "model": self.settings.deepgram_model,
            "smart_format": "true",
            "punctuate": "true",
            "diarize": "true",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers=headers,
                content=media_path.read_bytes(),
            )

        if response.status_code >= 400:
            raise TranscriptionError(
                f"Deepgram transcription failed with status {response.status_code}: {response.text[:400]}"
            )

        data = response.json()
        try:
            return (
                data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise TranscriptionError("Deepgram returned an unexpected response format.") from exc


def _looks_like_missing_audio_stream(text: str) -> bool:
    lowered = text.lower()
    return (
        "does not contain any stream" in lowered
        or "stream map 'a:0' matches no streams" in lowered
        or "contains no audio stream" in lowered
        or "no audio stream" in lowered
    )


def _short_ffmpeg_reason(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1][:240]
