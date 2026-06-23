from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ChapterRef:
    number: float | None
    title: str
    url: str
    volume: str | None = None
    order_hint: int = 0

    def sort_key(self) -> tuple[float, int, str]:
        num = self.number if self.number is not None else 10**9
        return (num, self.order_hint, self.title.lower())


@dataclass
class ChapterContent:
    ref: ChapterRef
    text: str
    source_url: str

    def safe_filename(self) -> str:
        number = f"{int(self.ref.number):04d}" if self.ref.number is not None and self.ref.number.is_integer() else (
            f"{self.ref.number:07.2f}".replace('.', '_') if self.ref.number is not None else f"{self.ref.order_hint:04d}"
        )
        safe = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in self.ref.title).strip()
        safe = ' '.join(safe.split())
        return f"{number} - {safe or 'chapter'}"


@dataclass
class NovelMetadata:
    title: str
    author: str | None = None
    description: str | None = None
    language: str = 'es'
    source_url: str | None = None
    parser_id: str | None = None
    cover_image_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExportResult:
    path: Path
    kind: str


@dataclass
class CrawlDiagnostics:
    stop_reason: str | None = None
    stop_detail: str | None = None
    current_url: str | None = None
    current_number: float | None = None
    next_url: str | None = None
    next_number: float | None = None
    visited_count: int = 0
    trace: list[str] = field(default_factory=list)


@dataclass
class RangeValidation:
    expected_start: float | None
    expected_end: float | None
    expected_count: int | None
    actual_start: float | None
    actual_end: float | None
    actual_count: int
    is_complete: bool
    reason: str | None = None
