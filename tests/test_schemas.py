import pytest
from pydantic import ValidationError

from app.api.schemas import (
    Config,
    Group,
    Room,
    SolveErrorResponse,
    SolveRequest,
    SolveResponse,
)


def test_solve_request_valid() -> None:
    payload = {
        "meta": {
            "version": "1.0.0",
            "school_term_id": 42,
            "webhook_url": "http://laravel-app/api/webhooks/allocation-result",
            "progress_webhook_url": "http://laravel-app/api/webhooks/allocation-progress",
        },
        "config": {
            "strict_capacity": False,
            "block_b_restriction_for_pos": True,
            "block_a_restriction_for_freshmen": False,
            "undergrad_in_block_a_penalty": 0.0,
            "pos_in_block_b_penalty": 0.0,
            "wasted_seats_weight": 1.5,
            "unassigned_penalty": 1000.0,
            "time_limit_seconds": 300,
        },
        "timeslots": [
            {
                "id": 0,
                "label": "seg_0800_0940",
                "day": "seg",
                "start": "08:00",
                "end": "09:40",
            },
        ],
        "rooms": [
            {"id": 1, "name": "B09", "capacity": 40},
        ],
        "groups": [
            {
                "id": 101,
                "type": "single",
                "class_ids": [101],
                "coddis": "MAC0110",
                "tiptur": "Graduacao",
                "demand": 55,
                "has_null_enrollment": False,
                "is_freshmen": False,
                "timeslot_ids": [0],
                "preassigned_room_id": None,
                "same_room_cohort": None,
            },
        ],
    }

    req = SolveRequest.model_validate(payload)
    assert req.meta.version == "1.0.0"
    assert req.meta.school_term_id == 42
    assert (
        str(req.meta.webhook_url) == "http://laravel-app/api/webhooks/allocation-result"
    )
    assert req.config.strict_capacity is False
    assert req.config.time_limit_seconds == 300
    assert len(req.timeslots) == 1
    assert req.timeslots[0].label == "seg_0800_0940"
    assert len(req.rooms) == 1
    assert req.rooms[0].capacity == 40
    assert len(req.groups) == 1
    assert req.groups[0].type == "single"
    assert req.groups[0].preassigned_room_id is None


def test_solve_request_invalid_missing_field() -> None:
    payload = {
        "meta": {
            "version": "1.0.0",
            "school_term_id": 42,
            "webhook_url": "http://laravel-app/api/webhooks/allocation-result",
            "progress_webhook_url": "http://laravel-app/api/webhooks/allocation-progress",
        },
        "config": {
            "strict_capacity": False,
            "block_b_restriction_for_pos": True,
            "block_a_restriction_for_freshmen": False,
            "undergrad_in_block_a_penalty": 0.0,
            "pos_in_block_b_penalty": 0.0,
            "wasted_seats_weight": 1.5,
            "unassigned_penalty": 1000.0,
            "time_limit_seconds": 300,
        },
        "timeslots": [],
        "rooms": [],
        # "groups" intentionally omitted
    }

    with pytest.raises(ValidationError) as exc_info:
        SolveRequest.model_validate(payload)

    assert "groups" in str(exc_info.value)


def test_solve_request_invalid_bad_type() -> None:
    payload = {
        "meta": {
            "version": "1.0.0",
            "school_term_id": 42,
            "webhook_url": "http://laravel-app/api/webhooks/allocation-result",
        },
        "config": {
            "strict_capacity": False,
            "block_b_restriction_for_pos": True,
            "block_a_restriction_for_freshmen": False,
            "undergrad_in_block_a_penalty": 0.0,
            "pos_in_block_b_penalty": 0.0,
            "wasted_seats_weight": 1.5,
            "unassigned_penalty": 1000.0,
            "time_limit_seconds": 300,
        },
        "timeslots": [
            {
                "id": 0,
                "label": "seg_0800_0940",
                "day": "seg",
                "start": "08:00",
                "end": "09:40",
            },
        ],
        "rooms": [
            {"id": 1, "name": "B09", "capacity": -5},  # invalid negative capacity
        ],
        "groups": [
            {
                "id": 101,
                "type": "single",
                "class_ids": [101],
                "coddis": "MAC0110",
                "tiptur": "Graduacao",
                "demand": 55,
                "has_null_enrollment": False,
                "is_freshmen": False,
                "timeslot_ids": [0],
                "preassigned_room_id": None,
                "same_room_cohort": None,
            },
        ],
    }

    with pytest.raises(ValidationError) as exc_info:
        SolveRequest.model_validate(payload)

    assert "capacity" in str(exc_info.value)


def test_solve_response_valid() -> None:
    payload = {
        "job_id": "uuid-1234-5678",
        "status": "optimal",
        "solve_time_seconds": 124.5,
        "solutions_found": 14,
        "objective_value": 450.5,
        "allocations": [
            {"group_id": 101, "room_id": 1},
        ],
        "unassigned_groups": [],
        "suggestions": [
            {"group_id": 310, "timeslot_id": 4, "suggested_room_id": 2},
        ],
    }

    resp = SolveResponse.model_validate(payload)
    assert resp.job_id == "uuid-1234-5678"
    assert resp.status == "optimal"
    assert resp.solve_time_seconds == 124.5
    assert resp.allocations[0].group_id == 101
    assert resp.suggestions[0].suggested_room_id == 2


def test_solve_error_response_valid() -> None:
    payload = {
        "job_id": "uuid-1234-5678",
        "status": "error",
        "message": "Something went wrong",
        "trace": "Traceback (most recent call last): ...",
    }

    resp = SolveErrorResponse.model_validate(payload)
    assert resp.status == "error"
    assert resp.message == "Something went wrong"


def test_config_negative_time_limit() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "strict_capacity": False,
                "block_b_restriction_for_pos": True,
                "block_a_restriction_for_freshmen": False,
                "undergrad_in_block_a_penalty": 0.0,
                "pos_in_block_b_penalty": 0.0,
                "wasted_seats_weight": 1.0,
                "unassigned_penalty": 100.0,
                "time_limit_seconds": 0,
            }
        )


def test_group_invalid_type() -> None:
    with pytest.raises(ValidationError):
        Group.model_validate(
            {
                "id": 101,
                "type": "invalid_type",
                "class_ids": [101],
                "coddis": "MAC0110",
                "tiptur": "Graduacao",
                "demand": 55,
                "has_null_enrollment": False,
                "is_freshmen": False,
                "timeslot_ids": [0],
                "preassigned_room_id": None,
                "same_room_cohort": None,
            }
        )


def test_room_default_available_for_auto() -> None:
    payload = {"id": 1, "name": "B09", "capacity": 40}
    room = Room.model_validate(payload)
    assert room.available_for_auto is True


def test_room_available_for_auto_false() -> None:
    payload = {"id": 1, "name": "B09", "capacity": 40, "available_for_auto": False}
    room = Room.model_validate(payload)
    assert room.available_for_auto is False
