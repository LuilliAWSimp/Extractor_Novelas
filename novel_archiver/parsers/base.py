from __future__ import annotations

from abc import ABC, abstractmethod
from bs4 import BeautifulSoup

from novel_archiver.http import HttpClient
from novel_archiver.models import ChapterContent, ChapterRef, NovelMetadata


class SiteParser(ABC):
    parser_id = 'base'
    display_name = 'Base parser'

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch_soup(self, url: str) -> BeautifulSoup:
        response = self.client.get(url)
        return BeautifulSoup(response.text, 'html.parser')

    @abstractmethod
    def discover(self, url: str) -> tuple[NovelMetadata, list[ChapterRef]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_chapter(self, chapter: ChapterRef) -> ChapterContent:
        raise NotImplementedError
