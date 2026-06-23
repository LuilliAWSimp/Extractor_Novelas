from __future__ import annotations

from pathlib import Path
from typing import Iterable

from novel_archiver.archive import safe_output_name
from novel_archiver.models import ChapterContent, ExportResult, NovelMetadata


def export_txt(metadata: NovelMetadata, chapters: Iterable[ChapterContent], output_dir: Path) -> ExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_output_name(str(metadata.extra.get('output_name') or metadata.title or 'novel'))
    path = output_dir / f'{filename}.txt'
    with path.open('w', encoding='utf-8') as f:
        f.write(metadata.title + '\n')
        if metadata.author:
            f.write(f'Autor: {metadata.author}\n')
        if metadata.source_url:
            f.write(f'Fuente: {metadata.source_url}\n')
        f.write('\n')
        for chapter in chapters:
            num = int(chapter.ref.number) if chapter.ref.number and chapter.ref.number.is_integer() else chapter.ref.number
            f.write(f"Capítulo {num}: {chapter.ref.title}\n")
            f.write('-' * 60 + '\n')
            f.write(chapter.text.strip() + '\n\n')
    return ExportResult(path=path, kind='txt')
