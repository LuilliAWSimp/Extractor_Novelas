from __future__ import annotations

import argparse
import logging
from pathlib import Path

from novel_archiver.runner import NovelArchiver, load_parser_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Archivador de novelas web autorizado')
    parser.add_argument('--url', help='URL índice/base de la novela')
    parser.add_argument('--chapter-list', help='Archivo de texto con lista manual de capítulos')
    parser.add_argument(
        '--parser',
        default='nova',
        choices=['nova', 'generic', 'novelaenespanol'],
        help='Parser a usar',
    )
    parser.add_argument('--output', default='novels_output', help='Carpeta raíz de salida')
    parser.add_argument('--formats', default='epub,txt', help='Formatos: txt,epub,pdf')
    parser.add_argument('--start', type=float, help='Primer capítulo a incluir')
    parser.add_argument('--end', type=float, help='Último capítulo a incluir')
    parser.add_argument('--limit', type=int, help='Máximo de capítulos a descargar')
    parser.add_argument('--seed-url', help='URL semilla del capítulo inicial para crawlers secuenciales')
    parser.add_argument('--ask-range', action='store_true', help='Pregunta por consola capítulo inicio/fin')
    parser.add_argument('--debug-crawl', action='store_true', help='Muestra trazas detalladas del crawler')
    parser.add_argument('--fail-incomplete', action='store_true', help='Falla si el rango solicitado queda incompleto')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay entre peticiones')
    parser.add_argument('--timeout', type=int, default=20, help='Timeout por petición')
    parser.add_argument('--retries', type=int, default=3, help='Reintentos HTTP')
    parser.add_argument('--config', help='JSON de configuración adicional para parser generic')
    parser.add_argument('--title', help='Título manual de la novela (útil con --chapter-list)')
    parser.add_argument('--author', help='Autor manual de la novela')
    parser.add_argument('--language', default='es', help='Idioma de la novela (default: es)')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    return parser


def _prompt_optional_float(prompt: str) -> float | None:
    raw = input(prompt).strip()
    if not raw:
        return None
    return float(raw)


def _prompt_optional_text(prompt: str) -> str | None:
    raw = input(prompt).strip()
    return raw or None


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.url and not args.chapter_list:
        parser.error('Debes indicar --url o --chapter-list')
    logging.basicConfig(level=getattr(logging, args.log_level), format='[%(levelname)s] %(message)s')

    if args.ask_range or (
        args.parser == 'novelaenespanol'
        and not args.chapter_list
        and args.start is None
        and args.end is None
        and args.limit is None
    ):
        print('Selección manual de capítulos')
        if args.parser == 'novelaenespanol' and not args.chapter_list:
            args.seed_url = _prompt_optional_text('URL del capítulo inicial (Enter para intentar descubrir desde índice): ')
            inferred = None
            if args.seed_url:
                import re
                m = re.search(r'capitulo-(\d+)(?:-|/|$)', args.seed_url, re.I)
                if m:
                    inferred = float(m.group(1))
            args.start = _prompt_optional_float('¿En qué número de capítulo iniciar? (Enter para inferir desde la URL): ')
            if args.start is None:
                args.start = inferred
        else:
            args.start = _prompt_optional_float('¿En qué capítulo iniciar? (Enter para sin límite): ')
        args.end = _prompt_optional_float('¿En qué capítulo terminar? (Enter para sin límite): ')

    archiver = NovelArchiver(Path(args.output), timeout=args.timeout, delay_seconds=args.delay, max_retries=args.retries)
    formats = [fmt.strip() for fmt in args.formats.split(',') if fmt.strip()]
    parser_config = load_parser_config(args.config)

    if args.chapter_list:
        metadata, chapters, exports = archiver.run_from_chapter_list(
            Path(args.chapter_list),
            args.parser,
            export_formats=formats,
            chapter_start=args.start,
            chapter_end=args.end,
            limit=args.limit,
            parser_config=parser_config,
            title=args.title,
            author=args.author,
            language=args.language,
            fail_incomplete=args.fail_incomplete,
        )
    else:
        metadata, chapters, exports = archiver.run(
            args.url,
            args.parser,
            export_formats=formats,
            chapter_start=args.start,
            chapter_end=args.end,
            limit=args.limit,
            parser_config=parser_config,
            debug_crawl=args.debug_crawl,
            fail_incomplete=args.fail_incomplete,
            seed_url=args.seed_url,
        )

    print(f'✅ Novela: {metadata.title}')
    print(f'✅ Capítulos exportados: {len(chapters)}')
    for path in exports:
        print(f'📦 {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
