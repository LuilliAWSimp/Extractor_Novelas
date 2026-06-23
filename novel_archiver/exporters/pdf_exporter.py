from __future__ import annotations

from pathlib import Path
from typing import Iterable

from novel_archiver.archive import safe_output_name
from novel_archiver.models import ChapterContent, ExportResult, NovelMetadata

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


def export_pdf(metadata: NovelMetadata, chapters: Iterable[ChapterContent], output_dir: Path) -> ExportResult | None:
    if not REPORTLAB_AVAILABLE:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_output_name(str(metadata.extra.get('output_name') or metadata.title or 'novel'))
    path = output_dir / f'{filename}.pdf'
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(metadata.title, styles['Title'])]
    if metadata.author:
        story += [Paragraph(f'Autor: {metadata.author}', styles['Normal']), Spacer(1, 12)]
    for chapter in chapters:
        num = int(chapter.ref.number) if chapter.ref.number and chapter.ref.number.is_integer() else chapter.ref.number
        story += [Spacer(1, 18), Paragraph(f'Capítulo {num}: {chapter.ref.title}', styles['Heading2'])]
        for paragraph in chapter.text.split('\n\n'):
            paragraph = paragraph.strip().replace('\n', ' ')
            if paragraph:
                story += [Paragraph(paragraph, styles['BodyText']), Spacer(1, 8)]
    doc.build(story)
    return ExportResult(path=path, kind='pdf')
