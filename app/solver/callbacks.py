"""Callbacks do OR-Tools CP-SAT para progresso e interrupção graciosa."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx
from ortools.sat.python import cp_model

if TYPE_CHECKING:
    import redis

logger = logging.getLogger(__name__)


class StopAwareCallback(cp_model.CpSolverSolutionCallback):
    """Callback que monitora sinais de parada no Redis e reporta progresso."""

    def __init__(
        self,
        job_id: str,
        redis_conn: redis.Redis,
        time_limit_seconds: int,
        progress_webhook_url: str | None = None,
        progress_offset: float = 15.0,
        progress_scale: float = 70.0,
        min_report_interval_seconds: float = 1.0,
        report_every_n_solutions: int = 10,
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._redis = redis_conn
        self._time_limit = time_limit_seconds
        self._progress_webhook_url = progress_webhook_url
        self._progress_offset = progress_offset
        self._progress_scale = progress_scale
        self._min_report_interval = min_report_interval_seconds
        self._report_every_n = report_every_n_solutions

        self._start_time = time.time()
        self._last_report_time = 0.0
        self.solution_count = 0
        self.was_stopped = False

    def on_solution_callback(self) -> None:
        self.solution_count += 1

        # Throttle: evitar flood no Redis.
        # A primeira solução sempre reporta para dar feedback imediato ao usuário.
        elapsed = time.time() - self._start_time
        should_report = (
            self.solution_count == 1
            or elapsed >= self._last_report_time + self._min_report_interval
            or self.solution_count % self._report_every_n == 0
        )

        if should_report:
            self._last_report_time = elapsed
            self._report_progress(elapsed)

        self._check_stop()

    def _report_progress(self, elapsed: float) -> None:
        progress = (
            self._progress_offset + (elapsed / self._time_limit) * self._progress_scale
        )
        progress = max(
            self._progress_offset,
            min(self._progress_offset + self._progress_scale, progress),
        )

        payload = {
            "job_id": self._job_id,
            "progress": round(progress, 2),
            "message": (
                "Otimizando distribuição "
                "(Isto pode demorar alguns minutos. "
                f"Soluções encontradas: {self.solution_count})..."
            ),
        }
        self._redis.setex(
            f"progress:job_{self._job_id}",
            3600,
            json.dumps(payload),
        )

        if self._progress_webhook_url:
            thread = threading.Thread(
                target=self._send_progress_webhook,
                args=(payload,),
                daemon=True,
            )
            thread.start()

    def _send_progress_webhook(self, payload: dict[str, Any]) -> None:
        try:
            response = httpx.post(
                self._progress_webhook_url,
                json=payload,
                timeout=3.0,
            )
            if response.status_code >= 400:
                logger.warning(
                    "Webhook de progresso retornou %s para job %s",
                    response.status_code,
                    self._job_id,
                )
        except httpx.RequestError:
            pass

    def _check_stop(self) -> None:
        if self._redis.exists(f"stop_job:{self._job_id}"):
            self.was_stopped = True
            self.StopSearch()
