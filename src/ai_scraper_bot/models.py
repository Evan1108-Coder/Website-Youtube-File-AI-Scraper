from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


SourceKind = Literal["youtube", "website", "file"]
VisualInputKind = Literal["image_url", "image_data"]
JobState = Literal[
    "queued",
    "extracting",
    "transcribing",
    "summarizing",
    "completed",
    "failed",
]


@dataclass(slots=True)
class JobSource:
    kind: SourceKind
    value: str
    attachment_name: str | None = None
    local_path: Path | None = None


@dataclass(slots=True)
class VisualInput:
    kind: VisualInputKind
    value: str
    label: str = ""


@dataclass(slots=True)
class ExtractedContent:
    title: str
    body: str
    source_label: str
    metadata: dict[str, str] = field(default_factory=dict)
    visual_inputs: list[VisualInput] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    runtime_diary: list[str] = field(default_factory=list)
    reviewed_media: list[str] = field(default_factory=list)
    video_interval_history: list[str] = field(default_factory=list)
    related_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JobResult:
    summary: str
    extracted: ExtractedContent
