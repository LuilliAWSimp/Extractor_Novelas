from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from novel_archiver.archive import ArchiveStore
from novel_archiver.exporters import export_epub, export_pdf, export_txt
from novel_archiver.http import HttpClient, HttpConfig
from novel_archiver.models import ChapterContent, ChapterRef, NovelMetadata, RangeValidation
from novel_archiver.parsers import GenericChapterListParser, NovaParser, NovelaEnEspanolParser

LOGGER = logging.getLogger(__name__)

PARSERS = {
    'nova': NovaParser,
    'generic': GenericChapterListParser,
    'novelaenespanol': NovelaEnEspanolParser,
}


class NovelArchiver:
    def __init__(self, output_root: Path, *, timeout: int = 20, delay_seconds: float = 1.0, max_retries: int = 3) -> None:
        self.output_root = output_root
        self.client = HttpClient(HttpConfig(timeout=timeout, delay_seconds=delay_seconds, max_retries=max_retries))
        self.store = ArchiveStore(output_root)

    def get_parser(self, parser_id: str, config: dict[str, Any] | None = None):
        if parser_id not in PARSERS:
            raise ValueError(f'Parser no soportado: {parser_id}')
        parser_cls = PARSERS[parser_id]
        if parser_id == 'generic':
            return parser_cls(self.client, config=config)
        return parser_cls(self.client)

    def run(
        self,
        base_url: str,
        parser_id: str,
        *,
        export_formats: list[str],
        chapter_start: float | None = None,
        chapter_end: float | None = None,
        limit: int | None = None,
        parser_config: dict[str, Any] | None = None,
        debug_crawl: bool = False,
        fail_incomplete: bool = False,
        seed_url: str | None = None,
        progress_callback=None,
        output_name: str | None = None,
    ) -> tuple[NovelMetadata, list[ChapterContent], list[Path]]:
        parser = self.get_parser(parser_id, config=parser_config)
        if hasattr(parser, 'discover_subset'):
            if progress_callback:
                progress_callback({'stage': 'discovering', 'message': 'Descubriendo capítulos...'})
            metadata, chapter_refs = parser.discover_subset(
                base_url,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                limit=limit,
                seed_url=seed_url,
                debug=debug_crawl,
            )
            subset_already_applied = True
        else:
            if progress_callback:
                progress_callback({'stage': 'discovering', 'message': 'Descubriendo capítulos...'})
            metadata, chapter_refs = parser.discover(base_url)
            subset_already_applied = False
        if output_name and str(output_name).strip():
            metadata.extra['output_name'] = str(output_name).strip()
        return self._download_and_export(
            metadata,
            chapter_refs,
            parser,
            export_formats=export_formats,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            limit=limit,
            subset_already_applied=subset_already_applied,
            fail_incomplete=fail_incomplete,
            progress_callback=progress_callback,
        )

    def run_from_chapter_list(
        self,
        chapter_list_path: Path,
        parser_id: str,
        *,
        export_formats: list[str],
        chapter_start: float | None = None,
        chapter_end: float | None = None,
        limit: int | None = None,
        parser_config: dict[str, Any] | None = None,
        title: str | None = None,
        author: str | None = None,
        language: str = 'es',
        fail_incomplete: bool = False,
        progress_callback=None,
        output_name: str | None = None,
    ) -> tuple[NovelMetadata, list[ChapterContent], list[Path]]:
        parser = self.get_parser(parser_id, config=parser_config)
        chapter_refs = load_chapter_list(chapter_list_path)
        if not chapter_refs:
            raise ValueError(f'El archivo de capítulos no contiene entradas válidas: {chapter_list_path}')
        metadata = NovelMetadata(
            title=(title or 'Sin título').strip() or 'Sin título',
            author=(author or None),
            language=(language or 'es').strip() or 'es',
            source_url=chapter_refs[0].url,
            parser_id=parser_id,
            extra={'chapter_list': str(chapter_list_path)},
        )
        return self._download_and_export(
            metadata,
            chapter_refs,
            parser,
            export_formats=export_formats,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            limit=limit,
            subset_already_applied=False,
            fail_incomplete=fail_incomplete,
            progress_callback=progress_callback,
        )

    def _download_and_export(
        self,
        metadata: NovelMetadata,
        chapter_refs: list[ChapterRef],
        parser,
        *,
        export_formats: list[str],
        chapter_start: float | None = None,
        chapter_end: float | None = None,
        limit: int | None = None,
        subset_already_applied: bool = False,
        fail_incomplete: bool = False,
        progress_callback=None,
        output_name: str | None = None,
    ) -> tuple[NovelMetadata, list[ChapterContent], list[Path]]:
        selected = chapter_refs if subset_already_applied else self._filter_chapters(chapter_refs, chapter_start, chapter_end, limit)
        LOGGER.info('Se detectaron %s capítulos; se descargarán %s', len(chapter_refs), len(selected))
        if chapter_refs:
            ordered = sorted(chapter_refs, key=lambda c: c.sort_key())
            LOGGER.info('Rango descubierto: %s -> %s', ordered[0].number, ordered[-1].number)
        diagnostics = getattr(parser, 'last_diagnostics', None)
        if diagnostics and diagnostics.stop_reason:
            LOGGER.info(
                'Crawler: current=%s current_num=%s next=%s next_num=%s stop=%s detail=%s',
                diagnostics.current_url,
                diagnostics.current_number,
                diagnostics.next_url,
                diagnostics.next_number,
                diagnostics.stop_reason,
                diagnostics.stop_detail,
            )
        if not selected:
            LOGGER.warning('No hay capítulos seleccionados con ese rango. Ajusta inicio/fin o usa el modo interactivo.')
        self.store.write_manifest(metadata, selected)

        contents: list[ChapterContent] = []
        if progress_callback:
            progress_callback({
                'stage': 'downloading',
                'message': f'Descubiertos {len(selected)} capítulos para descargar.',
                'current': 0,
                'total': len(selected),
            })
        for index, chapter in enumerate(selected, start=1):
            chapter_started = time.monotonic()
            LOGGER.info('Descargando capítulo %s -> %s', chapter.number, chapter.url)
            if progress_callback:
                progress_callback({
                    'stage': 'downloading',
                    'message': f'Descargando capítulo {chapter.number}',
                    'current': index - 1,
                    'total': len(selected),
                    'current_chapter': chapter.number,
                    'current_title': chapter.title,
                    'current_url': chapter.url,
                    'item_elapsed_seconds': 0.0,
                })
            content = parser.fetch_chapter(chapter)
            elapsed = time.monotonic() - chapter_started
            if not content.text.strip():
                LOGGER.warning('Capítulo vacío: %s', chapter.url)
                if progress_callback:
                    progress_callback({
                        'stage': 'downloading',
                        'message': f'Capítulo {chapter.number} vacío tras {elapsed:.1f}s',
                        'current': index,
                        'total': len(selected),
                        'current_chapter': chapter.number,
                        'current_title': chapter.title,
                        'current_url': chapter.url,
                        'item_elapsed_seconds': elapsed,
                    })
                continue
            contents.append(content)
            if progress_callback:
                progress_callback({
                    'stage': 'downloading',
                    'message': f'Capítulo {chapter.number} descargado en {elapsed:.1f}s',
                    'current': index,
                    'total': len(selected),
                    'current_chapter': chapter.number,
                    'current_title': chapter.title,
                    'current_url': chapter.url,
                    'item_elapsed_seconds': elapsed,
                })
        self.store.write_chapter_texts(metadata, contents)

        validation = self._validate_range(chapter_start, chapter_end, contents)
        metadata.extra['validation'] = validation.__dict__
        if diagnostics:
            metadata.extra['crawler_diagnostics'] = diagnostics.__dict__
        self._report_validation(validation, diagnostics)
        if fail_incomplete and not validation.is_complete:
            raise RuntimeError(validation.reason or 'El rango descargado quedó incompleto')

        export_dir = self.store.novel_dir(metadata) / 'exports'
        export_steps = [fmt for fmt in ('txt', 'epub', 'pdf') if fmt in export_formats]
        if progress_callback:
            progress_callback({
                'stage': 'exporting',
                'message': f'Exportando archivos ({len(export_steps)} formato(s))...',
                'current': 0,
                'total': len(export_steps),
                'current_chapter': None,
                'current_title': None,
                'current_url': None,
                'current_export': None,
                'item_elapsed_seconds': 0.0,
            })
        exports: list[Path] = []
        for export_index, fmt in enumerate(export_steps, start=1):
            export_started = time.monotonic()
            label = fmt.upper()
            LOGGER.info('Exportando %s...', label)
            if progress_callback:
                progress_callback({
                    'stage': 'exporting',
                    'message': f'Exportando {label} ({export_index}/{len(export_steps)})...',
                    'current': export_index - 1,
                    'total': len(export_steps),
                    'current_export': fmt,
                    'item_elapsed_seconds': 0.0,
                })
            if fmt == 'txt':
                exports.append(export_txt(metadata, contents, export_dir).path)
            elif fmt == 'epub':
                exports.append(export_epub(metadata, contents, export_dir).path)
            elif fmt == 'pdf':
                result = export_pdf(metadata, contents, export_dir)
                if result:
                    exports.append(result.path)
                else:
                    LOGGER.warning('PDF no generado: reportlab no está disponible')
            elapsed = time.monotonic() - export_started
            if progress_callback:
                progress_callback({
                    'stage': 'exporting',
                    'message': f'{label} exportado en {elapsed:.1f}s',
                    'current': export_index,
                    'total': len(export_steps),
                    'current_export': fmt,
                    'item_elapsed_seconds': elapsed,
                })
        if progress_callback:
            progress_callback({'stage': 'done', 'message': f'Proceso completo. Archivos generados: {len(exports)}', 'current': len(export_steps), 'total': len(export_steps), 'current_export': None, 'item_elapsed_seconds': None})
        return metadata, contents, exports

    @staticmethod
    def _filter_chapters(chapters: list[ChapterRef], start: float | None, end: float | None, limit: int | None) -> list[ChapterRef]:
        selected = []
        for chapter in sorted(chapters, key=lambda c: c.sort_key()):
            if start is not None and chapter.number is not None and chapter.number < start:
                continue
            if end is not None and chapter.number is not None and chapter.number > end:
                continue
            selected.append(chapter)
        if limit is not None:
            selected = selected[:limit]
        return selected

    @staticmethod
    def _validate_range(start: float | None, end: float | None, contents: list[ChapterContent]) -> RangeValidation:
        ordered = sorted(contents, key=lambda c: c.ref.sort_key())
        actual_start = ordered[0].ref.number if ordered else None
        actual_end = ordered[-1].ref.number if ordered else None
        actual_count = len(ordered)
        expected_count = None
        reason = None
        is_complete = True
        if start is not None and end is not None and end >= start:
            expected_count = int(end - start + 1)
            if actual_start != start or actual_end != end or actual_count != expected_count:
                is_complete = False
                reason = (
                    f'Rango incompleto: esperado {start}->{end} ({expected_count} capítulos), '
                    f'obtenido {actual_start}->{actual_end} ({actual_count} capítulos)'
                )
        return RangeValidation(
            expected_start=start,
            expected_end=end,
            expected_count=expected_count,
            actual_start=actual_start,
            actual_end=actual_end,
            actual_count=actual_count,
            is_complete=is_complete,
            reason=reason,
        )

    @staticmethod
    def _report_validation(validation: RangeValidation, diagnostics) -> None:
        LOGGER.info(
            'Validación final: esperado=%s->%s cantidad=%s | real=%s->%s cantidad=%s',
            validation.expected_start,
            validation.expected_end,
            validation.expected_count,
            validation.actual_start,
            validation.actual_end,
            validation.actual_count,
        )
        if not validation.is_complete:
            LOGGER.warning(validation.reason or 'El rango generado quedó incompleto')
            if diagnostics and diagnostics.stop_reason:
                LOGGER.warning('Motivo exacto de parada: %s (%s)', diagnostics.stop_reason, diagnostics.stop_detail)


def load_parser_config(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return json.loads(p.read_text(encoding='utf-8'))


def load_chapter_list(path: Path) -> list[ChapterRef]:
    if not path.exists():
        raise FileNotFoundError(path)

    chapters: list[ChapterRef] = []
    for line_no, raw_line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [part.strip() for part in line.split('|')]
        if len(parts) == 2:
            number_raw, url = parts
            title = ''
        elif len(parts) == 3:
            number_raw, title, url = parts
        else:
            raise ValueError(f'Línea inválida en {path} (línea {line_no}). Usa: numero|titulo|url o numero|url')
        if not url:
            raise ValueError(f'Línea inválida en {path} (línea {line_no}): URL vacía')
        try:
            number = float(number_raw)
        except ValueError as exc:
            raise ValueError(f'Línea inválida en {path} (línea {line_no}): número inválido {number_raw!r}') from exc
        final_title = title or default_chapter_title(number, len(chapters) + 1)
        chapters.append(ChapterRef(number=number, title=final_title, url=url, order_hint=len(chapters) + 1))
    chapters.sort(key=lambda c: c.sort_key())
    return chapters


def default_chapter_title(number: float | None, order_hint: int) -> str:
    if number is None:
        return f'Capítulo {order_hint}'
    if float(number).is_integer():
        return f'Capítulo {int(number)}'
    return f'Capítulo {number:g}'
