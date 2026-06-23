from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable

from ebooklib import epub

from novel_archiver.archive import safe_output_name
from novel_archiver.models import ChapterContent, ExportResult, NovelMetadata

DEFAULT_CSS = '''
body { font-family: serif; line-height: 1.5; }
h1 { text-align: center; }
h2 { margin-top: 1.5em; }
p { text-indent: 1.2em; margin: 0 0 0.8em 0; }
'''


def paragraphs_to_html(text: str) -> str:
    parts = []
    for paragraph in text.split('\n\n'):
        p = paragraph.strip().replace('\n', ' ')
        if not p:
            continue
        parts.append(f'<p>{escape(p)}</p>')
    return '\n'.join(parts)


def export_epub(metadata: NovelMetadata, chapters: Iterable[ChapterContent], output_dir: Path) -> ExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    book.set_title(metadata.title)
    book.set_language(metadata.language or 'es')
    if metadata.author:
        book.add_author(metadata.author)
    if metadata.source_url:
        book.add_metadata('DC', 'source', metadata.source_url)

    style = epub.EpubItem(uid='style_main', file_name='style/style.css', media_type='text/css', content=DEFAULT_CSS)
    book.add_item(style)

    spine = ['nav']
    toc = []
    for idx, chapter in enumerate(chapters, start=1):
        c = epub.EpubHtml(title=chapter.ref.title, file_name=f'chap_{idx:04d}.xhtml', lang=metadata.language)
        num = int(chapter.ref.number) if chapter.ref.number is not None and chapter.ref.number.is_integer() else chapter.ref.number
        c.content = (
            f'<html><head><link rel="stylesheet" href="style/style.css" /></head><body>'
            f'<h2>Capítulo {num}: {escape(chapter.ref.title)}</h2>'
            f'{paragraphs_to_html(chapter.text)}'
            f'</body></html>'
        )
        book.add_item(c)
        toc.append(c)
        spine.append(c)

    book.toc = tuple(toc)
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    filename = safe_output_name(str(metadata.extra.get('output_name') or metadata.title or 'novel'))
    path = output_dir / f'{filename}.epub'
    epub.write_epub(str(path), book, {})
    return ExportResult(path=path, kind='epub')
