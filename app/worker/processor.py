"""Helpers internos do worker RQ (conversão, montagem de resposta, I/O)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import redis

from app.api.schemas import (
    Allocation,
    Group,
    Room,
    SolveResponse,
    Suggestion,
    Timeslot,
)
from app.solver.engine import (
    GroupData,
    Pass1Result,
    Pass2Result,
    RoomData,
    SolverConfig,
    TimeslotData,
)

logger = logging.getLogger(__name__)


def _to_internal_config(config: Any) -> SolverConfig:
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
    """
    Dispara o webhook para o Laravel.

    Falhas de rede são isoladas via try/except para não contaminar
    o fluxo principal do worker.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
    except httpx.RequestError:
        logger.warning("Falha de rede ao enviar webhook para %s.", url)


def _save_result_to_redis(
    redis_conn: redis.Redis, job_id: str, payload: dict[str, Any]
) -> None:
    redis_conn.setex(f"result:{job_id}", 86400, json.dumps(payload))
