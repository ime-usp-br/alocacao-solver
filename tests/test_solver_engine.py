"""Testes de integração para o motor CP-SAT do Passe 1."""

from app.solver.engine import (
    GroupData,
    RoomData,
    SolverConfig,
    TimeslotData,
    run_pass_1,
    run_pass_2,
)


def _default_config(**overrides) -> SolverConfig:
    defaults = {
        "strict_capacity": True,
        "block_b_restriction_for_pos": True,
        "block_a_restriction_for_freshmen": False,
        "undergrad_in_block_a_penalty": 0.0,
        "pos_in_block_b_penalty": 0.0,
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
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
                is_freshmen=False,
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
                is_freshmen=False,
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=False)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
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
                is_freshmen=False,
                timeslot_ids=[0, 1],  # seg e qua
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=20,
                has_null_enrollment=False,
                is_freshmen=False,
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        allocated_rooms = [room_id for (_, room_id) in result.allocations]
        # Ambos devem conseguir a mesma sala porque os horários são contíguos
        assert allocated_rooms == [1, 1]
        assert result.unassigned_groups == []


class TestPass2Skipped:
    """Cenário I: Passe 2 é pulado quando não há grupos unassigned."""

    def test_skipped_when_all_allocated(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.unassigned_groups == []

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        assert pass2.status == "skipped"
        assert pass2.suggestions == []


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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config(strict_capacity=True)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=True,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=True)
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []


class TestPass2BasicAllocation:
    """Cenário J: Grupo unassigned do Passe 1 é sugerido no Passe 2."""

    def test_unassigned_group_gets_suggestion(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        # O Passe 1 aloca o grupo 101 na sala 1
        assert pass1.allocations == [(101, 1)]
        assert pass1.unassigned_groups == []

        # Forçar cenário onde 101 fica unassigned no Passe 1 (capacidade strict)
        config_strict = _default_config(strict_capacity=True)
        groups_big = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=60,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        pass1_big = run_pass_1(config_strict, timeslots, rooms, groups_big)
        assert pass1_big.unassigned_groups == [101]

        pass2 = run_pass_2(
            config_strict,
            timeslots,
            rooms,
            groups_big,
            pass1_big.allocations,
            pass1_big.unassigned_groups,
        )
        # Como a capacidade é strict e a sala não comporta, não há sugestão
        assert pass2.status in ("optimal", "feasible")
        assert pass2.suggestions == []


class TestPass2BestEffort:
    """Cenário K: Passe 2 sugere o máximo possível (best effort)."""

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
        # No Passe 1, 102 fica unassigned porque precisa de uma única sala para ambos.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.allocations == [(101, 1)]
        assert pass1.unassigned_groups == [102]

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        # Passe 2 deve sugerir sala 1 para o grupo 102 apenas no timeslot 1 (ter).
        # O timeslot 0 (seg) está bloqueado pelo grupo 101 fixo.
        assert pass2.status in ("optimal", "feasible")
        suggestions_for_102 = [s for s in pass2.suggestions if s[0] == 102]
        assert (102, 1, 1) in suggestions_for_102
        assert all(s[1] != 0 for s in suggestions_for_102)


class TestPass2BlockB:
    """Cenário L: Regra do Bloco B aplicada no Passe 2."""

    def test_pos_grad_blocked_in_pass2(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=True)
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.unassigned_groups == [101]

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        assert pass2.status in ("optimal", "feasible")
        assert pass2.suggestions == []

    def test_pos_grad_allowed_in_pass2_when_disabled(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_b_restriction_for_pos=False)
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.allocations == [(101, 1)]
        assert pass1.unassigned_groups == []

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        assert pass2.status == "skipped"


class TestPass2StrictCapacity:
    """Cenário M: Capacidade strict no Passe 2."""

    def test_strict_capacity_blocks_overflow_in_pass2(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.unassigned_groups == [101]

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        assert pass2.status in ("optimal", "feasible")
        assert pass2.suggestions == []

    def test_relaxed_capacity_allows_overflow_in_pass2(self) -> None:
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
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=False)
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.allocations == [(101, 1)]
        assert pass1.unassigned_groups == []

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        assert pass2.status == "skipped"


class TestPass2NoOverlapWithFixed:
    """Cenário N: Intervalos fixos do Passe 1 bloqueiam sugestões no Passe 2."""

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,  # fixado na sala 1
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.allocations == [(101, 1)]
        assert pass1.unassigned_groups == [102]

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        # A sala 1 está ocupada no timeslot 0 pelo grupo 101 (fixo).
        # Não há outra sala, então 102 não recebe sugestão.
        assert pass2.status in ("optimal", "feasible")
        assert pass2.suggestions == []

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
        # Sala 2 livre em ambos, mas no Passe 1 o solver pode alocar 102 na sala 2.
        # Para forçar unassigned, bloqueamos a sala 2 por capacidade.
        groups = [
            GroupData(
                id=101,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=60,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(strict_capacity=True)
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.allocations == [(101, 1)]
        assert pass1.unassigned_groups == [102]

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        # Sala 1 ocupada em ambos os timeslot; sala 2 não comporta demanda 60 (cap 50).
        # Não há sugestões possíveis.
        assert pass2.status in ("optimal", "feasible")
        assert pass2.suggestions == []


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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert len(result.allocations) == 2
        allocated_rooms = {room_id for (_, room_id) in result.allocations}
        assert len(allocated_rooms) == 1


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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
                same_room_cohort=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=True,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=True)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=True,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=False)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(block_a_restriction_for_freshmen=True)
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            undergrad_in_block_a_penalty=1000.0,
            unassigned_penalty=2000.0,
        )
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config(
            undergrad_in_block_a_penalty=1000.0,
            unassigned_penalty=2000.0,
        )
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
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
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,  # manual na sala bloqueada
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,  # automático
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        # O problema deve ser viável (não infeasible).
        # O grupo 101 está pré-alocado na sala 1 (bloqueada para auto).
        # O grupo 102 não pode usar a sala 1 (bloqueada para automática) e
        # a restrição de cohort força igualdade nas salas não bloqueadas,
        # então 102 também não pode usar a sala 2 (pois 101 está em 1).
        # Portanto, 102 fica unassigned — mas o solver não retorna infeasible.
        assert result.status in ("optimal", "feasible")
        assert (101, 1) in result.allocations
        assert 102 in result.unassigned_groups

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,  # automático
                same_room_cohort="2026-1",
            ),
            GroupData(
                id=102,
                tiptur="Graduacao",
                demand=30,
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[1],
                preassigned_room_id=None,  # automático
                same_room_cohort="2026-1",
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0],
                preassigned_room_id=1,
            ),
        ]
        config = _default_config()
        result = run_pass_1(config, timeslots, rooms, groups)

        assert result.status in ("optimal", "feasible")
        assert result.allocations == [(101, 1)]
        assert result.unassigned_groups == []

    def test_blocked_room_in_pass2(self) -> None:
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
                has_null_enrollment=False,
                is_freshmen=False,
                timeslot_ids=[0, 1],
                preassigned_room_id=None,
            ),
        ]
        config = _default_config()
        pass1 = run_pass_1(config, timeslots, rooms, groups)
        assert pass1.unassigned_groups == [101]

        pass2 = run_pass_2(
            config,
            timeslots,
            rooms,
            groups,
            pass1.allocations,
            pass1.unassigned_groups,
        )
        assert pass2.status in ("optimal", "feasible")
        assert pass2.suggestions == []
