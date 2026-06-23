from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from novel_archiver.models import ChapterContent, ChapterRef, CrawlDiagnostics, NovelMetadata
from novel_archiver.parsers.base import SiteParser
from novel_archiver.text_utils import extract_text_blocks, join_blocks, normalize_text

LOGGER = logging.getLogger(__name__)
TITLE_SUFFIX_RE = re.compile(r"\s+novela\s+español\s*$", re.I)
CHAPTER_RE = re.compile(r"(?:cap[ií]tulo|chapter)\s*(\d+(?:\.\d+)?)\s*(?:[:\-–]\s*(.+))?$", re.I)
AUTHOR_RE = re.compile(r"^el autor:\s*(.+)$", re.I)
TRANSLATION_RE = re.compile(r"^traducci[oó]n:\s*(.+)$", re.I)
STOP_MARKERS = (
    "leer lord of the mysteries en español",
    "leer el señor de los misterios en español",
    "el autor:",
    "traducción:",
    "traduccion:",
    "votar!",
    "mensajes del capítulo",
    "mensajes del capitulo",
    "escribe algunas líneas",
    "escribe algunas lineas",
    "publique un comentario",
    "publicar un comentario",
    "inicie sesión con su identificación social",
    "inicie sesión con su identificacion social",
    "seleccione una novela",
    "paginas",
)
SKIP_PREFIXES = (
    "hogar",
    "todos los capítulos",
    "todos los capitulos",
    "novela :",
    "el señor de los misterios – capítulo",
    "el señor de los misterios - capítulo",
    "el señor de los misterios – capitulo",
    "el señor de los misterios - capitulo",
    "capítulo ",
    "capitulo ",
)
ARROW_TEXTS = {">", ">>", "›", "»", "siguiente", "siguiente capítulo", "siguiente capitulo"}
PREV_ARROW_TEXTS = {"<", "<<", "‹", "«", "anterior", "capítulo anterior", "capitulo anterior"}


class NovelaEnEspanolParser(SiteParser):
    parser_id = "novelaenespanol"
    display_name = "novelaenespanol.com"

    def __init__(self, client):
        super().__init__(client)
        self.last_diagnostics = CrawlDiagnostics()

    def discover(self, url: str) -> tuple[NovelMetadata, list[ChapterRef]]:
        metadata = self._base_metadata(url)

        indexed = self._discover_from_index(url)
        if len(indexed) >= 30:
            self._stop("index_discovery", f"count={len(indexed[:30])}")
            return metadata, indexed[:30]

        soup = self.fetch_soup(url)
        chapter_one_url = self._find_chapter_one_url(soup, url)
        if not chapter_one_url:
            raise ValueError("No pude localizar el enlace a Capítulo 1 desde la página base")

        chapters = self._crawl_from_seed(
            chapter_one_url,
            chapter_start=None,
            chapter_end=None,
            limit=30,
            debug=False,
        )
        return metadata, chapters

    def discover_subset(
        self,
        url: str,
        *,
        chapter_start: float | None = None,
        chapter_end: float | None = None,
        limit: int | None = None,
        seed_url: str | None = None,
        debug: bool = False,
    ) -> tuple[NovelMetadata, list[ChapterRef]]:
        metadata = self._base_metadata(url)

        indexed = self._discover_from_index(
            url,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )

        use_index = False
        if indexed:
            if chapter_start is not None and chapter_end is not None and chapter_end >= chapter_start:
                expected_count = int(chapter_end - chapter_start + 1)
                numbers = [c.number for c in indexed if c.number is not None]
                contiguous = (
                    len(numbers) == expected_count
                    and numbers[0] == chapter_start
                    and numbers[-1] == chapter_end
                    and all(numbers[i] == chapter_start + i for i in range(len(numbers)))
                )
                use_index = contiguous
                if debug:
                    self._trace(
                        f"index_discovery count={len(indexed)} expected={expected_count} contiguous={contiguous}"
                    )
            else:
                use_index = len(indexed) >= 30

        if use_index:
            if limit is not None:
                indexed = indexed[:limit]
            self._stop("index_discovery", f"count={len(indexed)}")
            return metadata, indexed

        if seed_url:
            seed = seed_url
        else:
            soup = self.fetch_soup(url)
            chapter_one_url = self._find_chapter_one_url(soup, url)
            if not chapter_one_url:
                raise ValueError("No pude localizar el enlace a Capítulo 1 desde la página base")
            seed = chapter_one_url

        if chapter_start is None and seed_url:
            inferred = self._chapter_number_from_text(seed)
            if inferred is not None:
                chapter_start = inferred

        effective_limit = limit
        if chapter_start is not None and chapter_end is not None and chapter_end >= chapter_start:
            effective_limit = int(chapter_end - chapter_start + 1)

        chapters = self._crawl_from_seed(
            seed,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            limit=effective_limit,
            debug=debug,
        )
        return metadata, chapters

    def _base_metadata(self, url: str) -> NovelMetadata:
        soup = self.fetch_soup(url)
        title = self._parse_title(soup) or "Sin título"
        description = self._parse_description(soup)
        metadata = NovelMetadata(
            title=title,
            author=None,
            description=description,
            language="es",
            source_url=url,
            parser_id=self.parser_id,
        )
        return metadata

    def _discover_from_index(
        self,
        base_url: str,
        *,
        chapter_start: float | None = None,
        chapter_end: float | None = None,
    ) -> list[ChapterRef]:
        soup = self.fetch_soup(base_url)
        base_netloc = urlparse(base_url).netloc

        seen_urls: set[str] = set()
        by_number: dict[float, ChapterRef] = {}

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            if "#comment-" in href.lower():
                continue

            full_url = urljoin(base_url, href).split("#", 1)[0]
            parsed = urlparse(full_url)

            if parsed.netloc and parsed.netloc != base_netloc:
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            label = normalize_text(anchor.get_text(" ", strip=True))
            number = self._chapter_number_from_text(full_url)
            if number is None:
                number = self._chapter_number_from_text(label)
            if number is None:
                continue

            if chapter_start is not None and number < chapter_start:
                continue
            if chapter_end is not None and number > chapter_end:
                continue

            parsed_label = self._parse_chapter_label(label)
            title = None
            if parsed_label:
                title = parsed_label[1]

            if not title:
                number_label = int(number) if float(number).is_integer() else number
                title = f"Capítulo {number_label}"

            ref = ChapterRef(
                number=number,
                title=title,
                url=full_url,
                volume=None,
                order_hint=int(number) if float(number).is_integer() else 0,
            )

            existing = by_number.get(number)
            if existing is None:
                by_number[number] = ref
            else:
                if self._url_dup_penalty(ref.url) < self._url_dup_penalty(existing.url):
                    by_number[number] = ref

        chapters = sorted(
            by_number.values(),
            key=lambda c: (c.number if c.number is not None else 10**9, c.url),
        )
        return chapters

    def _find_chapter_one_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        base_netloc = urlparse(base_url).netloc
        candidates: list[tuple[int, str]] = []

        for idx, anchor in enumerate(soup.select("a[href]"), start=1):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.netloc and parsed.netloc != base_netloc:
                continue

            label = normalize_text(anchor.get_text(" ", strip=True)).lower()
            path = parsed.path.lower()

            if label in {"capítulo 1", "capitulo 1"}:
                candidates.append((idx, full_url))
            elif "/capitulo-1-" in path or path.rstrip("/").endswith("/capitulo-1"):
                candidates.append((idx, full_url))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _crawl_from_seed(
        self,
        seed_url: str,
        *,
        chapter_start: float | None,
        chapter_end: float | None,
        limit: int | None,
        debug: bool = False,
    ) -> list[ChapterRef]:
        results: list[ChapterRef] = []
        seen_urls: set[str] = set()
        current_url = seed_url
        order = 1
        self.last_diagnostics = CrawlDiagnostics()

        while current_url and current_url not in seen_urls:
            seen_urls.add(current_url)
            self.last_diagnostics.visited_count = len(seen_urls)
            self.last_diagnostics.current_url = current_url

            try:
                soup = self.fetch_soup(current_url)
            except Exception as exc:  # noqa: BLE001
                self._stop("http_error", f"{type(exc).__name__}: {exc}")
                break

            page_heading = self._page_heading(soup)
            number = self._chapter_number_from_text(page_heading or "")
            if number is None:
                number = self._chapter_number_from_text(current_url)

            self.last_diagnostics.current_number = number

            title = self._page_chapter_title(soup) or (
                f"Capítulo {int(number)}" if number is not None and float(number).is_integer() else f"Capítulo {order}"
            )
            ref = ChapterRef(number=number, title=title, url=current_url, volume=None, order_hint=order)

            include = True
            if chapter_start is not None and number is not None and number < chapter_start:
                include = False
            if chapter_end is not None and number is not None and number > chapter_end:
                include = False

            if include:
                results.append(ref)

            if debug:
                self._trace(f"current={current_url} number={number} include={include} count={len(results)}")

            if limit is not None and len(results) >= limit:
                self._stop("limit_reached", f"limit={limit}")
                break

            if chapter_end is not None and number is not None and number >= chapter_end:
                self._stop("chapter_end_reached", f"current={number} end={chapter_end}")
                break

            next_url, next_num, next_kind = self._next_chapter_url(soup, current_url)
            self.last_diagnostics.next_url = next_url
            self.last_diagnostics.next_number = next_num

            if debug:
                self._trace(f"next={next_url} next_number={next_num} via={next_kind}")

            if not next_url:
                self._stop("next_url_not_found", f"current={current_url} number={number}")
                break

            if next_url in seen_urls:
                self._stop("url_repeated", f"next_url={next_url}")
                break

            current_url = next_url
            order += 1

        if self.last_diagnostics.stop_reason is None:
            self._stop("crawl_finished", "loop_completed")

        return results

    def _next_chapter_url(self, soup: BeautifulSoup, current_url: str) -> tuple[str | None, float | None, str | None]:
        current_num = self._chapter_number_from_text(current_url)
        candidates = self._collect_next_candidates(soup, current_url)

        if not candidates:
            return None, None, None

        if current_num is not None:
            exact_next = current_num + 1

            exact_matches = [c for c in candidates if c[1] is not None and c[1] == exact_next]
            if exact_matches:
                exact_matches.sort(key=self._candidate_sort_key)
                return exact_matches[0]

            nav_matches = [
                c for c in candidates
                if c[2] == "nav_arrow" and c[1] is not None and c[1] > current_num
            ]
            if nav_matches:
                nav_matches.sort(key=self._candidate_sort_key)
                return nav_matches[0]

            greater_matches = [c for c in candidates if c[1] is not None and c[1] > current_num]
            if greater_matches:
                greater_matches.sort(key=self._candidate_sort_key)
                return greater_matches[0]

        nav_any = [c for c in candidates if c[2] == "nav_arrow"]
        if nav_any:
            nav_any.sort(key=self._candidate_sort_key)
            return nav_any[0]

        candidates.sort(key=self._candidate_sort_key)
        return candidates[0]

    def _collect_next_candidates(self, soup: BeautifulSoup, current_url: str) -> list[tuple[str, float | None, str]]:
        current_num = self._chapter_number_from_text(current_url)
        dedup: dict[str, tuple[str, float | None, str]] = {}

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            full_url = urljoin(current_url, href).split("#", 1)[0]
            if not full_url or full_url == current_url:
                continue

            label = normalize_text(anchor.get_text(" ", strip=True))
            label_lower = label.lower()
            rel = " ".join(anchor.get("rel", [])).lower()
            cls = " ".join(anchor.get("class", [])).lower()
            title = (anchor.get("title") or "").lower()
            aria = (anchor.get("aria-label") or "").lower()

            num = self._chapter_number_from_text(full_url)
            if num is None:
                num = self._chapter_number_from_text(label)

            nextish = (
                label_lower in ARROW_TEXTS
                or "next" in rel
                or "siguiente" in title
                or "siguiente" in aria
                or "next" in cls
                or ("pagination" in cls and label_lower not in PREV_ARROW_TEXTS)
            )

            kind = "nav_arrow" if nextish else "number_link"

            if current_num is not None and num is not None and num <= current_num:
                continue

            if num is None and not nextish:
                continue

            existing = dedup.get(full_url)
            candidate = (full_url, num, kind)

            if existing is None:
                dedup[full_url] = candidate
            else:
                if existing[2] != "nav_arrow" and kind == "nav_arrow":
                    dedup[full_url] = candidate

        return list(dedup.values())

    def _candidate_sort_key(self, item: tuple[str, float | None, str]) -> tuple[int, float, int, str]:
        url, num, kind = item

        kind_priority = 0 if kind == "nav_arrow" else 1
        num_key = num if num is not None else 10**9
        dup_penalty = self._url_dup_penalty(url)

        return (kind_priority, num_key, dup_penalty, url)

    def _url_dup_penalty(self, url: str) -> int:
        dup_match = re.search(r"-(\d+)(?:/)?$", url.rstrip("/"))
        return int(dup_match.group(1)) if dup_match else 0

    def fetch_chapter(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.fetch_soup(chapter.url)
        article = soup.select_one("article") or soup.select_one("main") or soup.body
        assert article is not None

        for selector in [
            "header", "footer", "form", "aside", "nav", ".comments", ".comments-area", ".sidebar",
            "script", "style", "noscript", ".sharedaddy", ".jp-relatedposts", ".entry-meta",
            ".author-box", ".widget", ".yarpp-related", ".breadcrumbs", ".social-share",
        ]:
            for element in article.select(selector):
                element.decompose()

        blocks = extract_text_blocks(article)
        filtered: list[str] = []
        found_body = False

        for block in blocks:
            lower = block.lower()

            if any(marker in lower for marker in STOP_MARKERS):
                break

            if AUTHOR_RE.match(block) or TRANSLATION_RE.match(block):
                continue

            if not found_body:
                if self._looks_like_title_or_heading(lower, chapter):
                    continue
                found_body = True

            if block in {"***", "* * *"}:
                filtered.append("* * *")
                continue

            filtered.append(block)

        page_title = self._page_chapter_title(soup)
        if page_title:
            chapter.title = page_title

        text = join_blocks(filtered)
        return ChapterContent(ref=chapter, text=text, source_url=chapter.url)

    def _parse_title(self, soup: BeautifulSoup) -> str | None:
        title_tag = soup.select_one("h1")
        if not title_tag:
            return None

        title = normalize_text(title_tag.get_text(" ", strip=True))
        title = TITLE_SUFFIX_RE.sub("", title).strip(" -–")
        return title or None

    def _parse_description(self, soup: BeautifulSoup) -> str | None:
        parts: list[str] = []

        for selector in ["div.entry-content p", "article p"]:
            for node in soup.select(selector):
                text = normalize_text(node.get_text(" ", strip=True))
                if not text:
                    continue
                if text.lower().startswith("género:") or text.lower().startswith("genero:"):
                    continue
                if CHAPTER_RE.search(text):
                    continue
                parts.append(text)
                if len(parts) >= 3:
                    return "\n\n".join(parts)

        return "\n\n".join(parts) if parts else None

    def _page_heading(self, soup: BeautifulSoup) -> str | None:
        tag = soup.select_one("h1")
        if not tag:
            return None
        return normalize_text(tag.get_text(" ", strip=True)) or None

    def _parse_chapter_label(self, label: str) -> tuple[float, str | None] | None:
        text = label.replace("–", "-").strip()

        if "capítulo" not in text.lower() and "capitulo" not in text.lower():
            return None

        if "lord of the mysteries" in text.lower() or "señor de los misterios" in text.lower():
            idx = max(text.lower().rfind("capítulo"), text.lower().rfind("capitulo"))
            if idx >= 0:
                text = text[idx:]

        match = CHAPTER_RE.search(text)
        if not match:
            return None

        number = float(match.group(1))
        chapter_title = (match.group(2) or "").strip(" -–") or None
        return number, chapter_title

    def _page_chapter_title(self, soup: BeautifulSoup) -> str | None:
        candidates = [soup.select_one("h1"), soup.select_one("h2"), soup.select_one("title")]

        for tag in candidates:
            if not tag:
                continue
            text = normalize_text(tag.get_text(" ", strip=True))
            parsed = self._parse_chapter_label(text)
            if parsed:
                return parsed[1] or f"Capítulo {int(parsed[0]) if parsed[0].is_integer() else parsed[0]}"

        return None

    def _chapter_number_from_text(self, text: str) -> float | None:
        parsed = self._parse_chapter_label(normalize_text(text))
        if parsed:
            return parsed[0]

        slug_match = re.search(r"capitulo-(\d+)(?:-|/|$)", text, re.I)
        if slug_match:
            return float(slug_match.group(1))

        return None

    def _looks_like_title_or_heading(self, lower_text: str, chapter: ChapterRef) -> bool:
        if any(lower_text.startswith(prefix) for prefix in SKIP_PREFIXES):
            return True

        if lower_text == chapter.title.lower():
            return True

        if chapter.number is not None:
            number_label = int(chapter.number) if float(chapter.number).is_integer() else chapter.number
            if lower_text in {f"capítulo {number_label}", f"capitulo {number_label}"}:
                return True

        return False

    def _trace(self, message: str) -> None:
        self.last_diagnostics.trace.append(message)
        LOGGER.debug("[crawl] %s", message)

    def _stop(self, reason: str, detail: str) -> None:
        self.last_diagnostics.stop_reason = reason
        self.last_diagnostics.stop_detail = detail
        LOGGER.info("Motivo de parada del crawler: %s (%s)", reason, detail)