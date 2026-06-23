from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from novel_archiver.models import ChapterContent, ChapterRef, NovelMetadata
from novel_archiver.parsers.base import SiteParser
from novel_archiver.text_utils import extract_text_blocks, join_blocks, normalize_text


CHAPTER_RE = re.compile(r'capitulo\s+(\d+(?:\.\d+)?)\s*:\s*(.+)$', re.I)
AUTHOR_RE = re.compile(r'^autor:\s*(.+)$', re.I)
TRANSLATOR_RE = re.compile(r'Esta novela esta siendo traducida por.*?([A-ZÁÉÍÓÚÑa-záéíóúñ .]+)')


class NovaParser(SiteParser):
    parser_id = 'nova'
    display_name = 'NOVA / novelasligeras.net'

    def discover(self, url: str) -> tuple[NovelMetadata, list[ChapterRef]]:
        soup = self.fetch_soup(url)
        title_tag = soup.select_one('h1.product_title, h1.entry-title')
        title = normalize_text(title_tag.get_text(' ', strip=True)) if title_tag else 'Sin título'

        description_tag = soup.select_one('div.woocommerce-product-details__short-description, div#tab-description')
        description = normalize_text(description_tag.get_text('\n', strip=True)) if description_tag else None

        author = None
        text_blob = normalize_text(soup.get_text('\n', strip=True))
        translator_match = TRANSLATOR_RE.search(text_blob)
        if translator_match:
            author = translator_match.group(1).strip()

        metadata = NovelMetadata(
            title=title,
            author=author,
            description=description,
            language='es',
            source_url=url,
            parser_id=self.parser_id,
        )

        chapters: list[ChapterRef] = []
        seen_urls: set[str] = set()
        for anchor in soup.select('a'):
            label = normalize_text(anchor.get_text(' ', strip=True))
            match = CHAPTER_RE.match(label)
            if not match:
                continue
            href = anchor.get('href')
            if not href:
                continue
            full_url = urljoin(url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            number = float(match.group(1))
            chapter_title = match.group(2).strip()
            volume = self._infer_volume(anchor)
            chapters.append(
                ChapterRef(number=number, title=chapter_title, url=full_url, volume=volume, order_hint=len(chapters) + 1)
            )
        chapters.sort(key=lambda c: c.sort_key())
        return metadata, chapters

    def fetch_chapter(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.fetch_soup(chapter.url)
        article = soup.select_one('article') or soup.select_one('main') or soup.body
        assert article is not None

        for selector in [
            'header', 'footer', 'form', 'aside', 'nav', '.sharedaddy', '.comments-area',
            '.wp-block-buttons', '.jp-relatedposts', '.entry-meta', '.author-box',
            '.yarpp-related', '.code-block', '.widget', '.sidebar', 'script', 'style'
        ]:
            for element in article.select(selector):
                element.decompose()

        blocks = extract_text_blocks(article)
        filtered: list[str] = []
        for block in blocks:
            lower = block.lower()
            if lower.startswith('autor:'):
                continue
            if lower.startswith('mantente enterado'):
                break
            if 'this site uses user verification plugin' in lower:
                break
            if lower.startswith('nova: pues esta historia empieza'):
                continue
            if lower.startswith('publicidad'):
                continue
            filtered.append(block)

        chapter_title = self._chapter_title_from_page(soup) or chapter.title
        chapter.ref.title = chapter_title
        text = join_blocks(filtered)
        return ChapterContent(ref=chapter, text=text, source_url=chapter.url)

    def _chapter_title_from_page(self, soup: BeautifulSoup) -> str | None:
        h2_tags = soup.select('h2')
        for tag in h2_tags:
            text = normalize_text(tag.get_text(' ', strip=True))
            match = CHAPTER_RE.match(text)
            if match:
                return match.group(2).strip()
        return None

    def _infer_volume(self, anchor) -> str | None:
        parent = anchor.parent
        hops = 0
        while parent is not None and hops < 8:
            previous = parent.find_previous(['h2', 'h3', 'h4'])
            if previous:
                text = normalize_text(previous.get_text(' ', strip=True))
                if text.lower().startswith('volumen'):
                    return text
            parent = parent.parent
            hops += 1
        return None
