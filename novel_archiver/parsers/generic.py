from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from novel_archiver.models import ChapterContent, ChapterRef, NovelMetadata
from novel_archiver.parsers.base import SiteParser
from novel_archiver.text_utils import extract_text_blocks, join_blocks, normalize_text


class GenericChapterListParser(SiteParser):
    parser_id = 'generic'
    display_name = 'Generic chapter-list parser'

    def __init__(self, client, config: dict | None = None) -> None:
        super().__init__(client)
        self.config = config or {}

    def discover(self, url: str) -> tuple[NovelMetadata, list[ChapterRef]]:
        soup = self.fetch_soup(url)
        title_selector = self.config.get('title_selector', 'h1')
        title_node = soup.select_one(title_selector)
        title = normalize_text(title_node.get_text(' ', strip=True)) if title_node else 'Sin título'
        description_selector = self.config.get('description_selector')
        description = None
        if description_selector:
            desc_node = soup.select_one(description_selector)
            if desc_node:
                description = normalize_text(desc_node.get_text('\n', strip=True))
        metadata = NovelMetadata(title=title, description=description, source_url=url, parser_id=self.parser_id)

        link_selector = self.config.get('chapter_link_selector', 'a')
        chapter_title_pattern = re.compile(self.config.get('chapter_title_pattern', r'cap[ií]tulo\s+(\d+(?:\.\d+)?)\s*[:\-]?\s*(.+)?'), re.I)
        chapters: list[ChapterRef] = []
        seen: set[str] = set()
        for idx, anchor in enumerate(soup.select(link_selector), start=1):
            text = normalize_text(anchor.get_text(' ', strip=True))
            match = chapter_title_pattern.match(text)
            if not match:
                continue
            href = anchor.get('href')
            if not href:
                continue
            full_url = urljoin(url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            number = float(match.group(1)) if match.group(1) else float(idx)
            chapter_title = (match.group(2) or text).strip()
            chapters.append(ChapterRef(number=number, title=chapter_title, url=full_url, order_hint=idx))
        chapters.sort(key=lambda c: c.sort_key())
        return metadata, chapters

    def fetch_chapter(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.fetch_soup(chapter.url)
        content_selector = self.config.get('chapter_content_selector', 'article, main, .entry-content')
        container = soup.select_one(content_selector)
        if container is None:
            raise ValueError(f'No se encontró contenido con selector: {content_selector}')
        skip_selectors = self.config.get('skip_selectors', [])
        blocks = extract_text_blocks(container, skip_selectors=skip_selectors)
        text = join_blocks(blocks)
        return ChapterContent(ref=chapter, text=text, source_url=chapter.url)
