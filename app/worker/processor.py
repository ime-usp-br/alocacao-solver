"""Processador de jobs RQ: orquestra Pass 1 e Pass 2 do solver."""

from __future__ import annotations

import json
import traceback
from typing import Any

import httpx
import redis

from app.api.schemas import (
    Allocation,
    Group,
    Room,
    SolveErrorResponse,
    SolveRequest,
    SolveResponse,
    Suggestion,
    Timeslot,
)
from app.solver.callbacks import StopAwareCallback
from app.solver.engine import (
    GroupData,
    Pass1Result,
    Pass2Result,
    RoomData,
    SolverConfig,
    TimeslotData,
    run_pass_1,
    run_pass_2,
)

REDIS_URL = __import__("os").getenv("REDIS_URL", "redis://localhost:6379/0")


def _to_internal_config(config: SolveRequest) -> SolverConfig:
    return SolverConfig(
        strict_capacity=config.config.strict_capacity,
        block_b_restriction_for_pos=config.config.block_b_restriction_for_pos,
        wasted_seats_weight=config.config.wasted_seats_weight,
        unassigned_penalty=config.config.unassigned_penalty,
        time_limit_seconds=config.config.time_limit_seconds,
    )


def _to_internal_timeslots(timeslots: list[Timeslot]) -> list[TimeslotData]:
    return [
        TimeslotData(
            id=ts.id,
            day=ts.day,
            start=ts.start,
            end=ts.end,
        )
        for ts in timeslots
    ]


def _to_internal_rooms(rooms: list[Room]) -> list[RoomData]:
    return [
        RoomData(
            id=r.id,
            name=r.name,
            capacity=r.capacity,
        )
        for r in rooms
    ]


def _to_internal_groups(groups: list[Group]) -> list[GroupData]:
    return [
        GroupData(
            id=g.id,
            tiptur=g.tiptur,
            demand=g.demand,
            has_null_enrollment=g.has_null_enrollment,
            timeslot_ids=g.timeslot_ids,
            preassigned_room_id=g.preassigned_room_id,
        )
        for g in groups
    ]


def _build_solve_response(
    job_id: str,
    pass1: Pass1Result,
    pass2: Pass2Result,
    global_status: str,
) -> dict[str, Any]:
    allocations = [
        Allocation(group_id=g_id, room_id=r_id) for g_id, r_id in pass1.allocations
    ]
    suggestions = [
        Suggestion(group_id=g_id, timeslot_id=ts_id, suggested_room_id=r_id)
        for g_id, ts_id, r_id in pass2.suggestions
    ]

    response = SolveResponse(
        job_id=job_id,
        status=global_status,  # type: ignore[arg-type]
        solve_time_seconds=round(
            pass1.solve_time_seconds + pass2.solve_time_seconds, 3
        ),
        solutions_found=pass1.solutions_found + pass2.solutions_found,
        objective_value=pass1.objective_value,
        allocations=allocations,
        unassigned_groups=pass1.unassigned_groups,
        suggestions=suggestions,
    )
    return response.model_dump(mode="json")


def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
    except Exception:
        # Webhook é best-effort; falhas são toleradas pois o resultado
        # também fica armazenado no Redis.
        pass


def _save_result_to_redis(
    redis_conn: redis.Redis, job_id: str, payload: dict[str, Any]
) -> None:
    redis_conn.setex(f"result:{job_id}", 86400, json.dumps(payload))


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

        # ------------------------------------------------------------------
        # Pass 1
        # ------------------------------------------------------------------
        callback = StopAwareCallback(
            job_id=job_id,
            redis_conn=redis_conn,
            time_limit_seconds=config.time_limit_seconds,
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
                progress_offset=70.0,
                progress_scale=15.0,
            )

            pass2_config = SolverConfig(
                strict_capacity=config.strict_capacity,
                block_b_restriction_for_pos=config.block_b_restriction_for_pos,
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

        _send_webhook(webhook_url, response_payload)

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
        except Exception:
            pass

    finally:
        redis_conn.close()
