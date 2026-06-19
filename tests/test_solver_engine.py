"""Testes de integração para o motor CP-SAT do Passe 1."""

from app.solver.engine import (
    GroupData,
    RoomData,
    SolverConfig,
    TimeslotData,
    run_solver,
)


def _default_config(**overrides) -> SolverConfig:
    defaults = {
        "strict_capacity": True,
        "block_b_restriction_for_pos": True,
        "block_a_restriction_for_freshmen": False,
        "undergrad_in_block_a_penalty": 0.0,
        "pos_in_block_b_penalty": 0.0,
        "waste_penalty": 1.0,
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=2,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=False)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []

    def test_pos_grad_cannot_use_b_room_case_insensitive(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="b09", capacity=50),
            RoomData(id=2, name="B101", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Pos Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]


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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]
        # O custo mínimo deve conter pelo menos a penalidade de unassigned
        assert result.objective_value >= config.unassigned_penalty

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=False)
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        # Penalidade de unassigned é 1000 (default), waste é pequeno.
        # O solver deve alocar exatamente 1 grupo (cabe na sala) e deixar o outro unassigned.
        config = _default_config(unassigned_penalty=1000, waste_penalty=1)
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0, 1],  # seg e qua
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=20,
                is_freshmen=False,
                timeslot_ids=[2],  # qua (conflita com o timeslot 1 do grupo 101)
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        # Ambos pré-alocados na mesma sala no mesmo horário -> impossível.
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status == "infeasible"
        assert result.allocations == []
        assert result.unassigned_groups == []


class TestScenarioSameTimeslotDifferentRooms:
    """AC1: 2 grupos no mesmo horário, 2 salas. Nunca podem ocupar a mesma sala."""

    def test_groups_never_share_same_room(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        allocated_rooms = [room_id for (_, room_id) in result.allocations]
        assert len(allocated_rooms) == len(set(allocated_rooms)), (
            "Duas turmas no mesmo horário foram alocadas na mesma sala"
        )
        assert result.unassigned_groups == []


class TestScenarioSameTimeslotSameRoomInfeasible:
    """AC1 (fronteira): 2 grupos pré-alocados no mesmo horário e mesma sala -> infeasible."""

    def test_two_groups_preassigned_same_room_same_timeslot_is_infeasible(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status == "infeasible"
        assert result.allocations == []
        assert result.unassigned_groups == []


class TestScenarioContiguousTimeslotsSameRoom:
    """AC1 (limites contíguos): horários encadeados devem permitir mesma sala."""

    def test_contiguous_timeslots_allow_same_room(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="10:00"),
            TimeslotData(id=1, day="seg", start="10:00", end="12:00"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        allocated_rooms = [room_id for (_, room_id) in result.allocations]
        # Ambos devem conseguir a mesma sala porque os horários são contíguos
        assert allocated_rooms == [1, 1]
        assert result.unassigned_groups == []


class TestScenarioPiecewisePrefersComfortZoneOverClaustrophobia:
    """Issue #40: solver prefere sala dentro da zona de conforto vs claustrofobia."""

    def test_prefers_comfort_zone_over_claustrophobia(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            # Sala que causaria claustrofobia (margem livre = 6.25% < 10%)
            RoomData(id=1, name="A242", capacity=32),
            # Sala dentro da zona de conforto (margem livre = 25%)
            RoomData(id=2, name="B09", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            comfort_zone_min_percent=10.0,
            comfort_zone_max_percent=25.0,
            claustrophobia_penalty=100.0,
            waste_penalty=1.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 2)]
        assert result.unassigned_groups == []


class TestScenarioPiecewisePrefersComfortZoneOverWaste:
    """Issue #40: solver prefere sala dentro da zona de conforto vs waste excessivo."""

    def test_prefers_comfort_zone_over_waste(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            # Sala que causaria waste (margem livre = 50% > 25%)
            RoomData(id=1, name="A242", capacity=60),
            # Sala dentro da zona de conforto (margem livre = 25%)
            RoomData(id=2, name="B09", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            comfort_zone_min_percent=10.0,
            comfort_zone_max_percent=25.0,
            claustrophobia_penalty=100.0,
            waste_penalty=10.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 2)]
        assert result.unassigned_groups == []


class TestScenarioPiecewiseComfortZoneHasZeroCost:
    """Issue #40: alocação dentro da zona de conforto gera custo zero."""

    def test_comfort_zone_allocation_has_zero_cost(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            # Sala dentro da zona de conforto (margem livre = 25%)
            RoomData(id=1, name="A242", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            comfort_zone_min_percent=10.0,
            comfort_zone_max_percent=25.0,
            claustrophobia_penalty=100.0,
            waste_penalty=10.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []
        assert result.objective_value == 0.0


class TestScenarioPreassignedOverridesCapacity:
    """Pré-alocação manual deve ignorar restrição de capacidade."""

    def test_preassigned_in_small_room_is_feasible(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=10),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=50,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioPreassignedOverridesBlockB:
    """Pré-alocação manual deve ignorar restrição do Bloco B."""

    def test_preassigned_pos_grad_in_block_b_is_feasible(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioPreassignedOverridesBlockA:
    """Pré-alocação manual deve ignorar restrição do Bloco A para calouros."""

    def test_preassigned_freshmen_in_block_a_is_feasible(self) -> None:
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
                is_freshmen=True,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioSplitClassBestEffort:
    """Cenário K: Solver unificado sugere alocações parciais quando um horário está bloqueado."""

    def test_partial_allocation_when_one_timeslot_blocked_by_fixed(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
        ]
        # Grupo 101 está fixo na sala 1 no seg (timeslot 0).
        # Grupo 102 precisa de seg E ter, mas sala 1 só está livre no ter.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert (101, 1) in result.allocations
        # 102 não pode ter uma única sala para todos os horários, portanto vai
        # para unassigned_groups com uma sugestão parcial no ter.
        assert 102 in result.unassigned_groups
        suggestions_for_102 = [s for s in result.suggestions if s[0] == 102]
        assert (102, 1, 1) in suggestions_for_102
        assert all(s[1] != 0 for s in suggestions_for_102)


class TestScenarioSplitClassPenalty:
    """Cenário K.1: Penalidade de split class influencia a escolha do solver."""

    def test_split_class_penalty_prevents_split(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),  # exata, sem waste
            RoomData(id=2, name="B09", capacity=40),  # waste de 10 assentos
        ]
        # O grupo 101 está fixo na sala 1 no seg, bloqueando-a para o grupo 102.
        # O grupo 102 precisa de seg e ter. No seg só pode usar a sala 2.
        # No ter pode usar a sala 1 (sem waste) ou a sala 2 (com waste).
        # Com split_class_penalty alto, o solver mantém 102 inteiramente na sala 2.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            split_class_penalty=100.0,
            waste_penalty=1.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        # 102 deve ficar integralmente na sala 2 para evitar a penalidade de split.
        assert (102, 2) in result.allocations
        assert 102 not in result.unassigned_groups

    def test_low_split_class_penalty_allows_split(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),
            RoomData(id=2, name="B09", capacity=40),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        # Com split_class_penalty menor que o waste poupado, o solver pode
        # dividir 102 entre as salas 2 (seg) e 1 (ter).
        config = _default_config(
            split_class_penalty=5.0,
            waste_penalty=1.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert 102 in result.unassigned_groups
        suggestions_for_102 = {s[1:3] for s in result.suggestions if s[0] == 102}
        assert (0, 2) in suggestions_for_102
        assert (1, 1) in suggestions_for_102


class TestScenarioNoOverlapWithFixed:
    """Cenário N: Intervalos fixos bloqueiam alocações no mesmo horário."""

    def test_fixed_interval_blocks_same_timeslot(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,  # fixado na sala 1
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        # A sala 1 está ocupada no timeslot 0 pelo grupo 101 (fixo).
        # Não há outra sala, então 102 fica totalmente sem sala.
        assert result.status in ("optimal", "feasible")
        assert (101, 1) in result.allocations
        assert result.unassigned_groups == [102]
        assert result.suggestions == []

    def test_fixed_interval_allows_different_timeslot(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50),
            RoomData(id=2, name="B09", capacity=50),
        ]
        # Grupo 101 fixo na sala 1 no seg.
        # Grupo 102 precisa de seg e ter; sala 1 ocupada em ambos.
        # Sala 2 livre em ambos, mas bloqueada por capacidade.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=60,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_solver(config, timeslots, rooms, groups)

        # Sala 1 ocupada em ambos os timeslot; sala 2 não comporta demanda 60 (cap 50).
        # 102 fica totalmente sem sala.
        assert result.status in ("optimal", "feasible")
        assert (101, 1) in result.allocations
        assert result.unassigned_groups == [102]
        assert result.suggestions == []


class TestScenarioCohortSameRoom:
    """Cenário O: Grupos do mesmo cohort devem ser alocados na mesma sala."""

    def test_cohort_groups_share_same_room(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
        ]
        # Penalidade alta o suficiente para manter o coorte unido.
        config = _default_config(split_cohort_penalty=1000.0)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        allocated_rooms = {room_id for (_, room_id) in result.allocations}
        assert len(allocated_rooms) == 1


class TestScenarioCohortCanSplitWhenPenaltyZero:
    """Cenário O.1: Com split_cohort_penalty=0, o coorte pode ser dividido."""

    def test_cohort_splits_without_penalty(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),
            RoomData(id=2, name="B09", capacity=30),
        ]
        # Dois grupos do mesmo coorte no mesmo horário. Sem penalidade de
        # divisão, o solver deve alocar cada um em uma sala diferente.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config(split_cohort_penalty=0.0)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        allocated_rooms = {room_id for (_, room_id) in result.allocations}
        assert len(allocated_rooms) == 2


class TestScenarioCohortSplitsWhenNoSingleRoomFits:
    """Cenário O.2: Coorte é dividido ao invés de retornar infeasible."""

    def test_cohort_splits_when_same_room_is_impossible(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),
            RoomData(id=2, name="B09", capacity=30),
        ]
        # Dois grupos do mesmo coorte no mesmo horário. Nenhuma sala cabe
        # ambos simultaneamente, então o solver deve dividir o coorte.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config(split_cohort_penalty=100.0)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        assert result.unassigned_groups == []
        allocated_rooms = {room_id for (_, room_id) in result.allocations}
        assert len(allocated_rooms) == 2


class TestScenarioCohortSplitPenaltyInObjective:
    """Cenário O.3: A divisão do coorte é refletida no valor objetivo."""

    def test_split_cohort_penalty_appears_in_objective(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),
            RoomData(id=2, name="B09", capacity=30),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
        ]
        split_penalty = 100.0
        config = _default_config(split_cohort_penalty=split_penalty)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        # Cada sala é usada exatamente uma vez, portanto extra_rooms = 1.
        assert result.objective_value == split_penalty


class TestScenarioCohortPriority:
    """Cenário P: Grupos de coorte têm prioridade absoluta sobre grupos sem coorte."""

    def test_cohort_group_gets_priority(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == [102]


class TestScenarioBlockAFreshmenHardConstraint:
    """Cenário Q: Proteção de Calouros no Bloco A (Hard Constraint)."""

    def test_freshmen_blocked_in_block_a(self) -> None:
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
                is_freshmen=True,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]

    def test_freshmen_allowed_in_block_a_when_disabled(self) -> None:
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
                is_freshmen=True,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=False)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []

    def test_non_freshmen_can_use_block_a(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioUndergradPrefersBlockB:
    """Cenário R: Soft Constraint direciona Graduação para o Bloco B."""

    def test_undergrad_prefers_block_b(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            undergrad_in_block_a_penalty=1000.0,
            unassigned_penalty=2000.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 2)]
        assert result.unassigned_groups == []


class TestScenarioUndergradAcceptsBlockAWhenNoOption:
    """Cenário S: Soft Constraint cede quando Bloco B não está disponível."""

    def test_undergrad_accepts_block_a_when_only_option(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            undergrad_in_block_a_penalty=1000.0,
            unassigned_penalty=2000.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioPosGradPrefersBlockA:
    """Cenário T: Soft Constraint direciona Pós-Graduação para o Bloco A."""

    def test_pos_grad_prefers_block_a(self) -> None:
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
                tiptur="Pos Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            block_b_restriction_for_pos=False,
            pos_in_block_b_penalty=1000.0,
            unassigned_penalty=2000.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestScenarioCohortWithBlockedRoom:
    """Cenário O.5: Cohort com anchor pré-alocado em sala bloqueada para auto."""

    def test_cohort_with_preassigned_anchor_in_blocked_room_is_feasible(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50, available_for_auto=False),
            RoomData(id=2, name="B09", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,  # manual na sala bloqueada
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,  # automático
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        # O problema deve ser viável (não infeasible).
        # O grupo 101 está pré-alocado na sala 1 (bloqueada para auto).
        # O grupo 102 não pode usar a sala 1 (bloqueada para automática).
        # Como a restrição de cohort agora é soft, 102 pode ser alocado na
        # sala 2, pagando a penalidade de divisão (split_cohort_penalty=0).
        assert result.status in ("optimal", "feasible")
        assert (101, 1) in result.allocations
        assert (102, 2) in result.allocations
        assert result.unassigned_groups == []

    def test_cohort_with_auto_anchor_blocked_room_allows_other_room(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50, available_for_auto=False),
            RoomData(id=2, name="B09", capacity=50),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,  # automático
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,  # automático
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        # Ambos devem estar na mesma sala, e essa sala deve ser a 2 (B09),
        # pois a sala 1 está bloqueada para automática.
        allocated_rooms = {room_id for (_, room_id) in result.allocations}
        assert len(allocated_rooms) == 1
        assert 2 in allocated_rooms


class TestScenarioRoomNotAvailableForAuto:
    """Cenário U: Salas bloqueadas para distribuição automática."""

    def test_auto_group_cannot_use_blocked_room(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50, available_for_auto=False),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]

    def test_preassigned_group_can_use_blocked_room(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50, available_for_auto=False),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []

    def test_blocked_room_cannot_be_suggested(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
            TimeslotData(id=1, day="ter", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=50, available_for_auto=False),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_solver(config, timeslots, rooms, groups)

        # A sala está bloqueada para automática e não há pré-alocação.
        assert result.status in ("optimal", "feasible")
        assert result.unassigned_groups == [101]
        assert result.suggestions == []


class TestScenarioStrictCapacityMixedDobradinha:
    """Issue #49: dobradinha 43+0 deve ser barrada por strict_capacity."""

    def test_mixed_dobradinha_blocked_by_strict_capacity(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=43,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == []
        assert result.unassigned_groups == [101]


class TestScenarioZeroDemandPrefersSmallestRoom:
    """Issue #49: turma com demanda 0 é permitida, mas waste_penalty empurra para a menor sala."""

    def test_zero_demand_group_prefers_smallest_room(self) -> None:
        timeslots = [
            TimeslotData(id=0, day="seg", start="08:00", end="09:40"),
        ]
        rooms = [
            RoomData(id=1, name="A242", capacity=30),
            RoomData(id=2, name="B09", capacity=10),
        ]
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=0,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            strict_capacity=True,
            waste_penalty=1.0,
            comfort_zone_min_percent=0.0,
            comfort_zone_max_percent=0.0,
        )
        result = run_solver(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 2)]
        assert result.unassigned_groups == []
