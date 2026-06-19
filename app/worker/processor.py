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
    RoomData,
    SolverConfig,
    SolverResult,
    TimeslotData,
)

logger = logging.getLogger(__name__)


def _to_internal_config(config: Any) -> SolverConfig:
    return SolverConfig(
        strict_capacity=config.config.strict_capacity,
        block_b_restriction_for_pos=config.config.block_b_restriction_for_pos,
        block_a_restriction_for_freshmen=config.config.block_a_restriction_for_freshmen,
        undergrad_in_block_a_penalty=config.config.undergrad_in_block_a_penalty,
        pos_in_block_b_penalty=config.config.pos_in_block_b_penalty,
        waste_penalty=config.config.waste_penalty,
        unassigned_penalty=config.config.unassigned_penalty,
        time_limit_seconds=config.config.time_limit_seconds,
        claustrophobia_penalty=config.config.claustrophobia_penalty,
        comfort_zone_min_percent=config.config.comfort_zone_min_percent,
        comfort_zone_max_percent=config.config.comfort_zone_max_percent,
        split_class_penalty=config.config.split_class_penalty,
        split_cohort_penalty=config.config.split_cohort_penalty,
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
            available_for_auto=r.available_for_auto,
        )
        for r in rooms
    ]


def _to_internal_groups(groups: list[Group]) -> list[GroupData]:
    return [
        GroupData(
            id=g.id,
            tiptur=g.tiptur,
            demand=g.demand,
            is_freshmen=g.is_freshmen,
            timeslot_ids=g.timeslot_ids,
            preassigned_room_id=g.preassigned_room_id,
            same_room_cohort=g.same_room_cohort,
        )
        for g in groups
    ]


def _build_solve_response(
    job_id: str,
    result: SolverResult,
    global_status: str,
) -> dict[str, Any]:
    allocations = [
        Allocation(group_id=g_id, room_id=r_id) for g_id, r_id in result.allocations
    ]
    suggestions = [
        Suggestion(group_id=g_id, timeslot_id=ts_id, suggested_room_id=r_id)
        for g_id, ts_id, r_id in result.suggestions
    ]

    response = SolveResponse(
        job_id=job_id,
        status=global_status,  # type: ignore[arg-type]
        solve_time_seconds=round(result.solve_time_seconds, 3),
        solutions_found=result.solutions_found,
        objective_value=result.objective_value,
        allocations=allocations,
        unassigned_groups=result.unassigned_groups,
        suggestions=suggestions,
    )
    return response.model_dump(mode="json")


def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    """
    Dispara o webhook para o Laravel.

    Falhas de rede e erros HTTP (4xx/5xx) são isoladas via try/except
    para não contaminar o fluxo principal do worker.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Webhook retornou HTTP %s para %s: %s",
            exc.response.status_code,
            url,
            exc.response.text,
        )
    except httpx.RequestError:
        logger.warning("Falha de rede ao enviar webhook para %s.", url)


def _save_result_to_redis(
    redis_conn: redis.Redis, job_id: str, payload: dict[str, Any]
) -> None:
    redis_conn.setex(f"result:{job_id}", 86400, json.dumps(payload))
