from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from novel_archiver.runner import NovelArchiver

LOGGER = logging.getLogger(__name__)


class WerkzeugStatusFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'GET /api/status/' not in record.getMessage()


def _install_werkzeug_status_filter() -> None:
    logger = logging.getLogger('werkzeug')
    if not any(isinstance(existing, WerkzeugStatusFilter) for existing in logger.filters):
        logger.addFilter(WerkzeugStatusFilter())


@dataclass
class JobState:
    job_id: str
    status: str = 'queued'
    stage: str = 'Pendiente'
    message: str = 'Esperando inicio'
    progress_current: int = 0
    progress_total: int = 0
    stage_code: str | None = None
    current_chapter: float | None = None
    current_title: str | None = None
    current_url: str | None = None
    current_export: str | None = None
    item_elapsed_seconds: float | None = None
    logs: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    output_dir: str | None = None
    title: str | None = None
    validation: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def append_log(self, message: str) -> None:
        line = message.rstrip()
        if line:
            self.logs.append(line)
            self.logs = self.logs[-400:]
            self.last_activity_at = time.time()

    def touch(self) -> None:
        self.last_activity_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        end_time = self.finished_at or time.time()
        data['elapsed_seconds'] = max(0.0, end_time - self.created_at)
        data['idle_seconds'] = max(0.0, time.time() - self.last_activity_at)
        return data


class JobLogHandler(logging.Handler):
    def __init__(self, job: JobState) -> None:
        super().__init__()
        self.job = job
        self.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.name == 'werkzeug' and ('GET /api/status/' in message or 'POST /api/start' in message or 'POST /api/open-output/' in message):
                return
            self.job.append_log(self.format(record))
        except Exception:
            pass


JOBS: dict[str, JobState] = {}
JOBS_LOCK = threading.Lock()


def create_app() -> Flask:
    _install_werkzeug_status_filter()
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.post('/api/start')
    def start_job():
        payload = request.get_json(silent=True) or request.form.to_dict(flat=True)
        job = JobState(job_id=uuid.uuid4().hex)
        with JOBS_LOCK:
            JOBS[job.job_id] = job
        threading.Thread(target=_run_job, args=(job, payload), daemon=True).start()
        return jsonify({'job_id': job.job_id})

    @app.get('/api/status/<job_id>')
    def get_status(job_id: str):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return jsonify({'error': 'Trabajo no encontrado'}), 404
        return jsonify(job.to_dict())

    @app.post('/api/open-output/<job_id>')
    def open_output(job_id: str):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return jsonify({'ok': False, 'error': 'Trabajo no encontrado'}), 404
        if not job.output_dir:
            return jsonify({'ok': False, 'error': 'Aún no hay carpeta de salida disponible'}), 400
        _open_path(Path(job.output_dir))
        return jsonify({'ok': True})

    return app


def _run_job(job: JobState, payload: dict[str, Any]) -> None:
    handler = JobLogHandler(job)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    root_logger.addHandler(handler)
    try:
        job.status = 'running'
        output_root = Path((payload.get('output') or 'novels_output').strip() or 'novels_output')
        parser_id = (payload.get('parser') or 'novelaenespanol').strip() or 'novelaenespanol'
        url = (payload.get('url') or '').strip()
        if not url:
            raise ValueError('Debes indicar la URL base de la novela')

        start = _to_optional_float(payload.get('start'))
        end = _to_optional_float(payload.get('end'))
        seed_url = (payload.get('seed_url') or '').strip() or None
        output_name = (payload.get('output_name') or '').strip() or None
        formats = payload.get('formats') or ['epub', 'txt']
        if isinstance(formats, str):
            formats = [fmt.strip() for fmt in formats.split(',') if fmt.strip()]
        else:
            formats = [str(fmt).strip() for fmt in formats if str(fmt).strip()]
        if not formats:
            raise ValueError('Selecciona al menos un formato')

        debug_crawl = _to_bool(payload.get('debug_crawl'))
        fail_incomplete = _to_bool(payload.get('fail_incomplete'))
        timeout = int(payload.get('timeout') or 20)
        delay = float(payload.get('delay') or 1.0)
        retries = int(payload.get('retries') or 3)

        requested_count = _estimate_requested_count(start, end)
        if requested_count and requested_count > 50:
            job.append_log(
                f'[AVISO] Rango grande detectado: {requested_count} capítulos. '
                'Para rangos grandes conviene generar primero TXT y después EPUB/PDF si el texto quedó correcto.'
            )

        archiver = NovelArchiver(output_root, timeout=timeout, delay_seconds=delay, max_retries=retries)

        metadata, chapters, exports = archiver.run(
            url,
            parser_id,
            export_formats=formats,
            chapter_start=start,
            chapter_end=end,
            debug_crawl=debug_crawl,
            fail_incomplete=fail_incomplete,
            seed_url=seed_url,
            progress_callback=lambda event: _handle_progress(job, event),
            output_name=output_name,
        )

        job.title = metadata.title
        job.exports = [str(path) for path in exports]
        if exports:
            job.output_dir = str(Path(exports[0]).parent)
        else:
            base_name = metadata.extra.get('output_name') or metadata.title
            job.output_dir = str((output_root / str(base_name)).resolve())
        job.validation = metadata.extra.get('validation')
        job.diagnostics = metadata.extra.get('crawler_diagnostics')
        job.stage = 'Completado'
        job.message = f'Se generaron {len(exports)} archivo(s) con {len(chapters)} capítulo(s).'
        job.progress_current = job.progress_total or len(chapters)
        job.status = 'done'
        job.finished_at = time.time()
        job.append_log('Proceso finalizado correctamente.')
    except Exception as exc:
        job.status = 'error'
        job.stage = 'Error'
        job.error = str(exc)
        job.message = str(exc)
        job.finished_at = time.time()
        job.append_log(f'[ERROR] {exc}')
        LOGGER.exception('Fallo en ejecución web')
    finally:
        root_logger.removeHandler(handler)


def _handle_progress(job: JobState, event: dict[str, Any]) -> None:
    stage = event.get('stage')
    message = event.get('message')
    if stage:
        stage_map = {
            'discovering': 'Descubriendo capítulos',
            'downloading': 'Descargando capítulos',
            'exporting': 'Exportando archivos',
            'done': 'Completado',
        }
        job.stage_code = str(stage)
        job.stage = stage_map.get(stage, str(stage))
    if 'current_chapter' in event:
        job.current_chapter = event.get('current_chapter')
    if 'current_title' in event:
        job.current_title = event.get('current_title')
    if 'current_url' in event:
        job.current_url = event.get('current_url')
    if 'current_export' in event:
        job.current_export = event.get('current_export')
    if 'item_elapsed_seconds' in event:
        value = event.get('item_elapsed_seconds')
        if isinstance(value, (int, float)):
            job.item_elapsed_seconds = float(value)
        elif value is None:
            job.item_elapsed_seconds = None
    if message:
        job.message = message
        job.append_log(message)
    else:
        job.touch()
    current = event.get('current')
    total = event.get('total')
    if isinstance(current, int):
        job.progress_current = current
    if isinstance(total, int):
        job.progress_total = total


def _open_path(path: Path) -> None:
    target = str(path.resolve())
    if sys.platform.startswith('win'):
        os.startfile(target)  # type: ignore[attr-defined]
        return
    if sys.platform == 'darwin':
        subprocess.Popen(['open', target])
        return
    try:
        subprocess.Popen(['xdg-open', target])
    except Exception:
        webbrowser.open(path.resolve().as_uri())


def _estimate_requested_count(start: float | None, end: float | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    if not float(start).is_integer() or not float(end).is_integer():
        return None
    return int(end - start + 1)


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'on', 'yes', 'si'}


app = create_app()
