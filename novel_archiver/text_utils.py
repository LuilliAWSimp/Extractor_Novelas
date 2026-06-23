from __future__ import annotations

import html
import re
from bs4 import BeautifulSoup


WHITESPACE_RE = re.compile(r'[\t\r\f\v ]+')
MULTI_BLANK_RE = re.compile(r'\n{3,}')
AD_RE = re.compile(r'^(publicidad|indice|índice|siguiente|anterior|pestaña anterior|pestaña siguiente)\b', re.I)


def normalize_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace('\xa0', ' ')
    text = text.replace('\u200b', '')
    text = text.replace('\u2060', '')
    lines = []
    for raw_line in text.splitlines():
        line = WHITESPACE_RE.sub(' ', raw_line).strip()
        if not line:
            lines.append('')
            continue
        lines.append(line)
    text = '\n'.join(lines)
    text = MULTI_BLANK_RE.sub('\n\n', text)
    return text.strip()


def extract_text_blocks(container: BeautifulSoup, *, skip_selectors: list[str] | None = None) -> list[str]:
    skip_selectors = skip_selectors or []
    for selector in skip_selectors:
        for element in container.select(selector):
            element.decompose()

    blocks: list[str] = []
    for node in container.find_all(['p', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'li']):
        text = normalize_text(node.get_text('\n', strip=True))
        if not text:
            continue
        if AD_RE.match(text):
            continue
        blocks.append(text)
    return dedupe_nearby(blocks)


def dedupe_nearby(blocks: list[str]) -> list[str]:
    result: list[str] = []
    prev = None
    for block in blocks:
        if block == prev:
            continue
        result.append(block)
        prev = block
    return result


def join_blocks(blocks: list[str]) -> str:
    return '\n\n'.join(blocks).strip()
