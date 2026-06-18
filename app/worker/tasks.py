"""Entrypoint público das tarefas executadas pelo RQ Worker."""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

import httpx
import redis

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

logger = logging.getLogger(__name__)


def process_job(job_data: dict[str, Any]) -> None:
    """
    Entrypoint do RQ Worker. Executa o solver unificado,
    envia webhook e persiste no Redis.
    """
    job_id = job_data.get("job_id", "unknown")
    redis_conn = redis.from_url(REDIS_URL)

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
        redis_conn.close()
