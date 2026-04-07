from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError


@dataclass(slots=True)
class LoadedImage:
    image: Image.Image
    notes: list[str] = field(default_factory=list)


def load_image_with_fallback(file_path: Path) -> LoadedImage:
    try:
        return LoadedImage(image=_open_image_copy(file_path))
    except (UnidentifiedImageError, OSError) as exc:
        if file_path.suffix.lower() != ".avif":
            raise RuntimeError(f"This image file could not be opened: {file_path.name}") from exc

        try:
            image = _convert_avif_with_ffmpeg(file_path)
        except FileNotFoundError as ffmpeg_exc:
            raise RuntimeError(
                "This AVIF file could not be opened directly, and `ffmpeg` is not available for fallback decoding. "
                "Install ffmpeg and restart the bot, or reinstall the AVIF decoder plugin."
            ) from ffmpeg_exc
        except subprocess.TimeoutExpired as ffmpeg_exc:
            raise RuntimeError(
                "This AVIF file could not be decoded in time through the ffmpeg fallback."
            ) from ffmpeg_exc
        except subprocess.CalledProcessError as ffmpeg_exc:
            raise RuntimeError(
                "This AVIF file could not be decoded by Pillow or by the ffmpeg fallback."
            ) from ffmpeg_exc

        return LoadedImage(
            image=image,
            notes=[
                "The bot decoded this AVIF image through an ffmpeg fallback because Pillow could not open it directly."
            ],
        )


def _open_image_copy(file_path: Path) -> Image.Image:
    with Image.open(file_path) as image:
        image.load()
        return image.copy()


def _convert_avif_with_ffmpeg(file_path: Path) -> Image.Image:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(file_path),
                "-frames:v",
                "1",
                str(temp_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=30,
        )
        return _open_image_copy(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
