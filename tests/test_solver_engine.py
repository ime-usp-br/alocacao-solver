"""Testes de integração para o motor CP-SAT do Passe 1."""

from app.solver.engine import (
    GroupData,
    RoomData,
    SolverConfig,
    TimeslotData,
    run_pass_1,
)


def _default_config(**overrides) -> SolverConfig:
    defaults = {
        "strict_capacity": True,
        "block_b_restriction_for_pos": True,
        "wasted_seats_weight": 1.0,
        "unassigned_penalty": 1000.0,
        "time_limit_seconds": 10,
    }
    defaults.update(overrides)
    return SolverConfig(**defaults)


class TestScenarioTrivialNoConflict:
    """Cenário A: 2 grupos em horários diferentes, 2 salas suficientes."""

    def test_both_allocated(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
            RoomData(id=2, name="B09", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        assert result.unassigned_groups == []


class TestScenarioConflictForcesChoice:
    """Cenário B: 2 grupos no mesmo horário, 1 sala."""

    def test_one_allocated_one_unassigned(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 1
        assert len(result.unassigned_groups) == 1


class TestScenarioPreassignedRoom:
    """Cenário C: Grupo com preassigned_room_id fixado."""

    def test_preassigned_respected(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
            RoomData(id=2, name="B09", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=2,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 2)]
        assert result.unassigned_groups == []


class TestScenarioBlockB:
    """Cenário D: Regra do Bloco B para Pós-Graduação."""

    def test_pos_grad_cannot_use_b_room(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="B09", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Pos Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]

    def test_pos_grad_can_use_b_room_when_disabled(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="B09", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Pos Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=False)
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioStrictCapacity:
    """Cenário E: Capacidade strict impede alocação."""

    def test_strict_capacity_blocks_overflow(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=50,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]

    def test_relaxed_capacity_allows_overflow(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=50,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=False)
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioObjectiveUnassignedPenalty:
    """Cenário G: Penalidade alta de unassigned influencia escolha."""

    def test_prefers_allocation_over_unassigned(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        # Penalidade de unassigned é 1000 (default), waste é pequeno.
        # O solver deve alocar exatamente 1 grupo (cabe na sala) e deixar o outro unassigned.
        config = _default_config(unassigned_penalty=1000, wasted_seats_weight=1)
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 1
        assert len(result.unassigned_groups) == 1


class TestScenarioMultiTimeslotNoOverlap:
    """Cenário H: Grupo com múltiplos timeslots e conflito parcial."""

    def test_conflict_only_on_overlapping_timeslot(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="qua", start="10:00", end="11:40"),
            TimeslotData(
                id=2, day="qua", start="10:00", end="11:40"
            ),  # mesmo horário do id=1
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=20,
                has_null_enrollment=False,
                timeslot_ids=[0, 1],  # seg e qua
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=20,
                has_null_enrollment=False,
                timeslot_ids=[2],  # qua (conflita com o timeslot 1 do grupo 101)
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        # Apenas um dos grupos pode usar a sala A242 na qua.
        # O grupo 101 precisa da sala tanto na seg quanto na qua.
        # Se 101 pegar a sala, 102 fica de fora. Se 102 pegar, 101 fica de fora (mas 101 tem 2 horários).
        # O solver deve alocar 101 (menor custo total, pois unassigned de 101 custa mais - 2 timeslots sem sala
        # mas na verdade U[g] é binária, então custo é o mesmo).
        # De qualquer forma, exatamente 1 dos dois deve estar alocado na sala.
        assert len(result.allocations) == 1
        assert len(result.unassigned_groups) == 1


class TestScenarioInfeasible:
    """Cenário onde o problema é matematicamente impossível."""

    def test_infeasible_when_preassigned_conflicts(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        # Ambos pré-alocados na mesma sala no mesmo horário -> impossível.
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status == "infeasible"
        assert result.allocations == []
        assert result.unassigned_groups == []
