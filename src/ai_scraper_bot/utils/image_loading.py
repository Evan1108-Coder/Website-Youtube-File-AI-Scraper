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

        signature = _inspect_avif_signature(file_path)
        if not signature.is_likely_avif:
            raise RuntimeError(
                "This file is named like an AVIF image, but its file header does not look like a valid AVIF image container. "
                f"Detected header info: {signature.summary}"
            ) from exc

        ffmpeg_detail = ""
        try:
            image = _convert_avif_with_ffmpeg(file_path)
        except FileNotFoundError as ffmpeg_exc:
            ffmpeg_detail = (
                "ffmpeg is not available for AVIF fallback decoding. "
                "Install ffmpeg and restart the bot."
            )
        except subprocess.TimeoutExpired as ffmpeg_exc:
            ffmpeg_detail = "ffmpeg timed out while trying to decode the AVIF file."
        except subprocess.CalledProcessError as ffmpeg_exc:
            ffmpeg_detail = _summarize_subprocess_error(
                ffmpeg_exc,
                default_message="ffmpeg could not decode the AVIF file.",
            )
        else:
            return LoadedImage(
                image=image,
                notes=[
                    "The bot decoded this AVIF image through an ffmpeg fallback because Pillow could not open it directly."
                ],
            )

        try:
            image = _convert_avif_with_sips(file_path)
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            pass
        except subprocess.CalledProcessError as sips_exc:
            sips_detail = _summarize_subprocess_error(
                sips_exc,
                default_message="macOS `sips` could not decode the AVIF file.",
            )
            raise RuntimeError(
                "This AVIF file could not be decoded by Pillow, ffmpeg, or the macOS `sips` fallback. "
                f"Details: {ffmpeg_detail} {sips_detail}".strip()
            ) from sips_exc
        else:
            return LoadedImage(
                image=image,
                notes=[
                    "The bot decoded this AVIF image through the macOS `sips` fallback because Pillow could not open it directly."
                ],
            )

        raise RuntimeError(
            "This AVIF file could not be decoded by Pillow or by the available fallback decoders. "
            f"Header info: {signature.summary}. Details: {ffmpeg_detail}".strip()
        ) from exc


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
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(file_path),
                "-frames:v",
                "1",
                str(temp_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return _open_image_copy(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _convert_avif_with_sips(file_path: Path) -> Image.Image:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "sips",
                "-s",
                "format",
                "png",
                str(file_path),
                "--out",
                str(temp_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return _open_image_copy(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _summarize_subprocess_error(exc: subprocess.CalledProcessError, *, default_message: str) -> str:
    stderr = (exc.stderr or "").strip()
    stdout = (exc.stdout or "").strip()
    detail = stderr or stdout
    if not detail:
        return default_message
    first_line = detail.splitlines()[0].strip()
    return f"{default_message} {first_line}"


@dataclass(slots=True)
class _AvifSignature:
    is_likely_avif: bool
    summary: str


def _inspect_avif_signature(file_path: Path) -> _AvifSignature:
    header = file_path.read_bytes()[:64]
    if len(header) < 12:
        return _AvifSignature(False, "file is too small to contain a valid AVIF/ISOBMFF header")

    if header[4:8] != b"ftyp":
        magic = header[:12].hex()
        return _AvifSignature(False, f"missing ISOBMFF ftyp box; first bytes={magic}")

    major_brand = header[8:12].decode("latin1", errors="replace")
    compatible_bytes = header[16:64]
    compatible_brands = [
        compatible_bytes[index:index + 4].decode("latin1", errors="replace")
        for index in range(0, len(compatible_bytes), 4)
        if len(compatible_bytes[index:index + 4]) == 4
    ]
    known_avif_brands = {"avif", "avis"}
    known_related_brands = {"mif1", "msf1", "heic", "heix", "hevc", "hevx"}
    all_brands = {major_brand, *compatible_brands}
    if all_brands & known_avif_brands:
        return _AvifSignature(
            True,
            f"major_brand={major_brand}; compatible_brands={', '.join(compatible_brands) or 'none'}",
        )
    if all_brands & known_related_brands:
        return _AvifSignature(
            False,
            f"header looks like a related HEIF/HEIC-style container instead of AVIF; major_brand={major_brand}; compatible_brands={', '.join(compatible_brands) or 'none'}",
        )
    return _AvifSignature(
        False,
        f"unrecognized ISOBMFF brands; major_brand={major_brand}; compatible_brands={', '.join(compatible_brands) or 'none'}",
    )
