"""Entrypoint público das tarefas executadas pelo RQ Worker."""

from __future__ import annotations

import json
import logging
import threading
import traceback
from typing import Any

import httpx
import redis
from rq.job import Job

from app.api.schemas import (
    SolveErrorResponse,
    SolveRequest,
)
from app.solver.callbacks import StopAwareCallback
from app.solver.engine import run_solver
from app.worker.processor import (
    _build_solve_response,
    _save_result_to_redis,
    _send_webhook,
    _to_internal_config,
    _to_internal_groups,
    _to_internal_rooms,
    _to_internal_timeslots,
)

REDIS_URL = __import__("os").getenv("REDIS_URL", "redis://localhost:6379/0")

# TTL do heartbeat: se o work-horse morrer (SIGKILL/OOM), a chave expira
# neste prazo e o sweeper detecta o job órfão.
HEARTBEAT_TTL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 15
# TTL do job_meta: deve sobreviver ao heartbeat para o sweeper poder ler
# o webhook_url mesmo depois do work-horse morrer.
JOB_META_TTL_SECONDS = 86400

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def _start_heartbeat(
    redis_conn: redis.Redis,
    job_id: str,
    stop_event: threading.Event,
) -> threading.Thread:
    """
    Inicia uma thread daemon que renova ``job_alive:{job_id}`` no Redis.

    A thread morre junto com o work-horse (SIGKILL), fazendo a chave expirar
    em ``HEARTBEAT_TTL_SECONDS`` — sinal para o sweeper de que o job morreu.
    """

    def _beat() -> None:
        key = f"job_alive:{job_id}"
        while not stop_event.is_set():
            try:
                redis_conn.setex(key, HEARTBEAT_TTL_SECONDS, "1")
            except Exception:
                logger.warning("Heartbeat falhou para job %s.", job_id)
            stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)

    thread = threading.Thread(target=_beat, daemon=True, name=f"heartbeat-{job_id}")
    thread.start()
    return thread


def _register_job_meta(
    redis_conn: redis.Redis,
    job_id: str,
    webhook_url: str,
    progress_webhook_url: str,
) -> None:
    """Persiste metadados do job para o sweeper poder notificar o Laravel."""
    redis_conn.setex(
        f"job_meta:{job_id}",
        JOB_META_TTL_SECONDS,
        json.dumps(
            {
                "webhook_url": webhook_url,
                "progress_webhook_url": progress_webhook_url,
            }
        ),
    )


def _cleanup_job_meta(redis_conn: redis.Redis, job_id: str) -> None:
    """Remove chaves de heartbeat/meta — chamada no finally do process_job."""
    redis_conn.delete(f"job_alive:{job_id}", f"job_meta:{job_id}")


# ---------------------------------------------------------------------------
# Callback de falha do RQ (safety-net para exceções, não SIGKILL)
# ---------------------------------------------------------------------------


def on_job_failure(job: Job, exc_string: str) -> None:
    """
    Callback de falha executado pelo RQ.

    Roda para exceções Python normais (não capturadas).  **Não** roda para
    SIGKILL/OOM — nesse caso o sweeper é quem notifica o Laravel.

    É idempotente: se já existe um resultado no Redis (salvo pelo
    ``process_job`` ou pelo sweeper), não faz nada.
    """
    job_id = job.id
    redis_conn = redis.from_url(REDIS_URL)

    try:
        if redis_conn.exists(f"result:{job_id}"):
            return

        job_data = job.args[0] if job.args else {}
        webhook_url = str(job_data.get("meta", {}).get("webhook_url", "")) or None

        error_payload = SolveErrorResponse(
            job_id=job_id,
            status="error",
            message=str(exc_string),
            trace=exc_string,
        ).model_dump(mode="json")

        _save_result_to_redis(redis_conn, job_id, error_payload)

        if webhook_url:
            try:
                _send_webhook(webhook_url, error_payload)
            except httpx.RequestError:
                logger.warning(
                    "Webhook de erro (on_failure) falhou para job %s.",
                    job_id,
                )
    finally:
        redis_conn.close()


# ---------------------------------------------------------------------------
# Entrypoint do RQ
# ---------------------------------------------------------------------------


def process_job(job_data: dict[str, Any]) -> None:
    """
    Entrypoint do RQ Worker. Executa o solver unificado,
    envia webhook e persiste no Redis.
    """
    job_id = job_data.get("job_id", "unknown")
    redis_conn = redis.from_url(REDIS_URL)
    stop_event = threading.Event()

    try:
        # ------------------------------------------------------------------
        # Parse e validação
        # ------------------------------------------------------------------
        request = SolveRequest.model_validate(job_data)
        config = _to_internal_config(request)
        timeslots = _to_internal_timeslots(request.timeslots)
        rooms = _to_internal_rooms(request.rooms)
        groups = _to_internal_groups(request.groups)
        webhook_url = str(request.meta.webhook_url)
        progress_webhook_url = str(request.meta.progress_webhook_url)

        # ------------------------------------------------------------------
        # Heartbeat + meta para o sweeper detectar morte abrupta (SIGKILL)
        # ------------------------------------------------------------------
        _register_job_meta(redis_conn, job_id, webhook_url, progress_webhook_url)
        _start_heartbeat(redis_conn, job_id, stop_event)

        # ------------------------------------------------------------------
        # Solver unificado
        # ------------------------------------------------------------------
        callback = StopAwareCallback(
            job_id=job_id,
            redis_conn=redis_conn,
            time_limit_seconds=config.time_limit_seconds,
            progress_webhook_url=progress_webhook_url,
            progress_offset=15.0,
            progress_scale=70.0,
        )

        result = run_solver(config, timeslots, rooms, groups, callback=callback)

        # ------------------------------------------------------------------
        # Montar resposta e entregar
        # ------------------------------------------------------------------
        global_status = "stopped" if callback.was_stopped else result.status
        response_payload = _build_solve_response(job_id, result, global_status)
        _save_result_to_redis(redis_conn, job_id, response_payload)

        # Marca 100% no progresso assim que o solver finaliza.
        redis_conn.setex(
            f"progress:job_{job_id}",
            3600,
            json.dumps(
                {"progress": 100.0, "message": "Otimização concluída com sucesso."}
            ),
        )

        # Isolamento de falha do webhook: falhas de rede não devem
        # sobrescrever o status de sucesso do job.
        try:
            _send_webhook(webhook_url, response_payload)
        except httpx.RequestError:
            logger.warning(
                "Webhook falhou para job %s, mas resultado está no Redis.",
                job_id,
            )

    except Exception as exc:
        # --------------------------------------------------------------
        # Tratamento de falha geral: nunca deixar o worker "morrer calado"
        # --------------------------------------------------------------
        error_payload = SolveErrorResponse(
            job_id=job_id,
            status="error",
            message=str(exc),
            trace=traceback.format_exc(),
        ).model_dump(mode="json")

        _save_result_to_redis(redis_conn, job_id, error_payload)

        try:
            webhook_url = str(job_data.get("meta", {}).get("webhook_url", ""))
            if webhook_url:
                _send_webhook(webhook_url, error_payload)
        except httpx.RequestError:
            logger.warning(
                "Webhook de erro falhou para job %s, mas resultado está no Redis.",
                job_id,
            )
        except Exception:
            logger.warning(
                "Falha inesperada ao enviar webhook de erro para job %s.",
                job_id,
            )

    finally:
        stop_event.set()
        _cleanup_job_meta(redis_conn, job_id)
        redis_conn.close()
