from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Input Schemas (Dispatch Request)
# ---------------------------------------------------------------------------


class Meta(BaseModel):
    version: str
    school_term_id: int
    webhook_url: HttpUrl
    progress_webhook_url: HttpUrl


class Config(BaseModel):
    strict_capacity: bool
    block_b_restriction_for_pos: bool
    wasted_seats_weight: float = Field(..., ge=0)
    unassigned_penalty: float = Field(..., ge=0)
    time_limit_seconds: int = Field(..., ge=1)


class Timeslot(BaseModel):
    id: int
    label: str
    day: str
    start: str
    end: str


class Room(BaseModel):
    id: int
    name: str
    capacity: int = Field(..., ge=0)


class Group(BaseModel):
    id: int
    type: Literal["single", "fusion"]
    class_ids: list[int]
    coddis: str
    tiptur: str
    demand: int = Field(..., ge=0)
    has_null_enrollment: bool
    timeslot_ids: list[int]
    preassigned_room_id: int | None
    same_room_cohort: str | None = None


class SolveRequest(BaseModel):
    meta: Meta
    config: Config
    timeslots: list[Timeslot]
    rooms: list[Room]
    groups: list[Group]


# ---------------------------------------------------------------------------
# Output Schemas (Webhook / Result)
# ---------------------------------------------------------------------------


class Allocation(BaseModel):
    group_id: int
    room_id: int


class Suggestion(BaseModel):
    group_id: int
    timeslot_id: int
    suggested_room_id: int


class SolveResponse(BaseModel):
    job_id: str
    status: Literal["optimal", "feasible", "stopped", "infeasible"]
    solve_time_seconds: float = Field(..., ge=0)
    solutions_found: int = Field(..., ge=0)
    objective_value: float
    allocations: list[Allocation]
    unassigned_groups: list[int]
    suggestions: list[Suggestion]


class SolveErrorResponse(BaseModel):
    job_id: str
    status: Literal["error"]
    message: str
    trace: str


class SolveAcceptedResponse(BaseModel):
    job_id: str
    status: Literal["queued"]
    message: str


class StopResponse(BaseModel):
    job_id: str
    message: str
