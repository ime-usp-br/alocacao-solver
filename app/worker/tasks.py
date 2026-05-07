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
from app.solver.engine import (
    Pass2Result,
    SolverConfig,
    run_pass_1,
    run_pass_2,
)
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
    Entrypoint do RQ Worker. Orquestra Pass 1 e Pass 2,
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
        # Pass 1
        # ------------------------------------------------------------------
        callback = StopAwareCallback(
            job_id=job_id,
            redis_conn=redis_conn,
            time_limit_seconds=config.time_limit_seconds,
            progress_webhook_url=progress_webhook_url,
            progress_offset=15.0,
            progress_scale=55.0,
        )

        pass1 = run_pass_1(config, timeslots, rooms, groups, callback=callback)

        # ------------------------------------------------------------------
        # Pass 2 (apenas se sobrarem grupos e tempo)
        # ------------------------------------------------------------------
        pass2: Pass2Result
        if pass1.unassigned_groups:
            elapsed = pass1.solve_time_seconds
            remaining = max(1, config.time_limit_seconds - int(elapsed))

            pass2_callback = StopAwareCallback(
                job_id=job_id,
                redis_conn=redis_conn,
                time_limit_seconds=remaining,
                progress_webhook_url=progress_webhook_url,
                progress_offset=70.0,
                progress_scale=15.0,
            )

            pass2_config = SolverConfig(
                strict_capacity=config.strict_capacity,
                block_b_restriction_for_pos=config.block_b_restriction_for_pos,
                block_a_restriction_for_freshmen=config.block_a_restriction_for_freshmen,
                undergrad_in_block_a_penalty=config.undergrad_in_block_a_penalty,
                pos_in_block_b_penalty=config.pos_in_block_b_penalty,
                wasted_seats_weight=config.wasted_seats_weight,
                unassigned_penalty=config.unassigned_penalty,
                time_limit_seconds=remaining,
            )

            pass2 = run_pass_2(
                config=pass2_config,
                timeslots=timeslots,
                rooms=rooms,
                groups=groups,
                pass1_allocations=pass1.allocations,
                pass1_unassigned_groups=pass1.unassigned_groups,
                callback=pass2_callback,
            )
        else:
            pass2 = Pass2Result(
                status="skipped",
                solve_time_seconds=0.0,
                suggestions=[],
                solutions_found=0,
            )

        # ------------------------------------------------------------------
        # Montar resposta e entregar
        # ------------------------------------------------------------------
        stopped = callback.was_stopped
        if pass1.unassigned_groups:
            stopped = stopped or pass2_callback.was_stopped

        global_status = "stopped" if stopped else pass1.status
        response_payload = _build_solve_response(job_id, pass1, pass2, global_status)
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
