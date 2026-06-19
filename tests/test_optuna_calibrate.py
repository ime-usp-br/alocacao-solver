"""Testes para as funções puras do script de calibração Optuna."""

from app.solver.engine import GroupData, RoomData, SolverResult
from scripts.optuna_calibrate import (
    calc_claustrophobia,
    calc_waste,
    count_split_classes,
    count_split_cohorts,
)


def _result(
    allocations: list[tuple[int, int]] | None = None,
    unassigned_groups: list[int] | None = None,
    suggestions: list[tuple[int, int, int]] | None = None,
) -> SolverResult:
    return SolverResult(
        status="optimal",
        solve_time_seconds=1.0,
        objective_value=0.0,
        allocations=allocations or [],
        unassigned_groups=unassigned_groups or [],
        suggestions=suggestions or [],
        solutions_found=1,
    )


class TestCountSplitClasses:
    def test_no_split_when_single_room(self) -> None:
        result = _result(
            unassigned_groups=[1],
            suggestions=[(1, 10, 100), (1, 11, 100)],
        )
        assert count_split_classes(result) == 0

    def test_split_when_multiple_rooms(self) -> None:
        result = _result(
            unassigned_groups=[1],
            suggestions=[(1, 10, 100), (1, 11, 200)],
        )
        assert count_split_classes(result) == 1

    def test_allocations_are_not_split(self) -> None:
        result = _result(allocations=[(1, 100)])
        assert count_split_classes(result) == 0


class TestCountSplitCohorts:
    def test_cohort_split_between_rooms(self) -> None:
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=10,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
                same_room_cohort="A",
            ),
            GroupData(
                id=2,
                tiptur="Graduacao",
                demand=10,
                is_freshmen=False,
                timeslot_ids=[2],
                preassigned_room_id=None,
                same_room_cohort="A",
            ),
        ]
        result = _result(
            allocations=[(1, 100), (2, 200)],
        )
        assert count_split_cohorts(result, groups) == 1

    def test_cohort_not_split(self) -> None:
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=10,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
                same_room_cohort="A",
            ),
            GroupData(
                id=2,
                tiptur="Graduacao",
                demand=10,
                is_freshmen=False,
                timeslot_ids=[2],
                preassigned_room_id=None,
                same_room_cohort="A",
            ),
        ]
        result = _result(
            allocations=[(1, 100), (2, 100)],
        )
        assert count_split_cohorts(result, groups) == 0

    def test_no_cohort_returns_zero(self) -> None:
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=10,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        result = _result(allocations=[(1, 100)])
        assert count_split_cohorts(result, groups) == 0


class TestCalcClaustrophobia:
    def test_claustrophobia_below_comfort_zone(self) -> None:
        rooms = [RoomData(id=1, name="A101", capacity=100)]
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=95,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        result = _result(allocations=[(1, 1)])
        # comfort_min = 10% -> free_seats_min = 10. free_seats = 5 < 10.
        # excess = 95 - (100 - 10) = 5.
        assert (
            calc_claustrophobia(result, rooms, groups, comfort_zone_min_percent=10.0)
            == 5
        )

    def test_no_claustrophobia_inside_comfort_zone(self) -> None:
        rooms = [RoomData(id=1, name="A101", capacity=100)]
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=80,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        result = _result(allocations=[(1, 1)])
        assert (
            calc_claustrophobia(result, rooms, groups, comfort_zone_min_percent=10.0)
            == 0
        )


class TestCalcWaste:
    def test_waste_above_comfort_zone(self) -> None:
        rooms = [RoomData(id=1, name="A101", capacity=100)]
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=50,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        result = _result(allocations=[(1, 1)])
        # comfort_max = 25% -> free_seats_max = 25. free_seats = 50 > 25.
        # excess = (100 - 25) - 50 = 25.
        assert calc_waste(result, rooms, groups, comfort_zone_max_percent=25.0) == 25

    def test_no_waste_inside_comfort_zone(self) -> None:
        rooms = [RoomData(id=1, name="A101", capacity=100)]
        groups = [
            GroupData(
                id=1,
                tiptur="Graduacao",
                demand=80,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        result = _result(allocations=[(1, 1)])
        assert calc_waste(result, rooms, groups, comfort_zone_max_percent=25.0) == 0
