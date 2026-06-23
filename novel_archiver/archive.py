from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from novel_archiver.models import ChapterContent, ChapterRef, NovelMetadata


def safe_output_name(value: str) -> str:
    safe = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in value).strip()
    safe = ' '.join(safe.split())
    return safe or 'novel'


class ArchiveStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def output_name(self, metadata: NovelMetadata) -> str:
        custom = metadata.extra.get('output_name') if metadata.extra else None
        base_name = str(custom or metadata.title or 'novel').strip()
        return safe_output_name(base_name)

    def novel_dir(self, metadata: NovelMetadata) -> Path:
        return self.root / self.output_name(metadata)

    def write_manifest(self, metadata: NovelMetadata, chapters: Iterable[ChapterRef]) -> Path:
        novel_dir = self.novel_dir(metadata)
        novel_dir.mkdir(parents=True, exist_ok=True)
        data = {
            'metadata': metadata.to_dict(),
            'chapters': [
                {'number': c.number, 'title': c.title, 'url': c.url, 'volume': c.volume, 'order_hint': c.order_hint}
                for c in chapters
            ],
        }
        path = novel_dir / 'manifest.json'
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return path

    def write_chapter_texts(self, metadata: NovelMetadata, chapters: Iterable[ChapterContent]) -> Path:
        novel_dir = self.novel_dir(metadata)
        text_dir = novel_dir / 'chapters_txt'
        text_dir.mkdir(parents=True, exist_ok=True)
        for chapter in chapters:
            path = text_dir / f'{chapter.safe_filename()}.txt'
            path.write_text(chapter.text, encoding='utf-8')
        return text_dir
