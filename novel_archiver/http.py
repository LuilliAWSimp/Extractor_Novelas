from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOGGER = logging.getLogger(__name__)


@dataclass
class HttpConfig:
    timeout: int = 20
    delay_seconds: float = 1.0
    max_retries: int = 3
    user_agent: str = (
        'NovelArchiver/0.1 (+local archival tool; respectful rate limit; '
        'only for authorized content)'
    )


class HttpClient:
    def __init__(self, config: Optional[HttpConfig] = None) -> None:
        self.config = config or HttpConfig()
        self.session = requests.Session()
        retry = Retry(
            total=self.config.max_retries,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(['GET', 'HEAD']),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({'User-Agent': self.config.user_agent})
        self._last_request_at = 0.0

    def get(self, url: str, **kwargs) -> requests.Response:
        self._respect_delay()
        timeout = kwargs.pop('timeout', self.config.timeout)
        LOGGER.debug('GET %s', url)
        response = self.session.get(url, timeout=timeout, **kwargs)
        response.raise_for_status()
        self._last_request_at = time.monotonic()
        return response

    def _respect_delay(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
