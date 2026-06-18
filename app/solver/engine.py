"""Motor matemático unificado do solver usando OR-Tools CP-SAT.

O modelo decide sobre a variável Y[g, t, r]: o grupo `g` utiliza a sala `r`
no horário `t`. Isso permite que uma mesma turma ocupe salas diferentes em
horários distintos (split class), eliminando a necessidade de dois passes.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass

from ortools.sat.python import cp_model

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# O CP-SAT não aceita floats na função objetivo.
# Multiplicamos os pesos por este fator e trabalhamos com inteiros.
SCALE = 1000


def _sanitize_tiptur(tiptur: str) -> str:
    """Remove acentos e normaliza para comparação case-insensitive."""
    return (
        unicodedata.normalize("NFKD", tiptur)
        .encode("ASCII", "ignore")
        .decode("utf-8")
        .lower()
    )


# ---------------------------------------------------------------------------
# Estruturas de dados internas (puros, sem dependência da API)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimeslotData:
    id: int
    day: str
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class RoomData:
    id: int
    name: str
    capacity: int
    available_for_auto: bool = True


@dataclass(frozen=True, slots=True)
class GroupData:
    id: int
    tiptur: str
    demand: int
    has_null_enrollment: bool
    is_freshmen: bool
    timeslot_ids: list[int]
    preassigned_room_id: int | None
    same_room_cohort: str | None = None


@dataclass(frozen=True, slots=True)
class SolverConfig:
    strict_capacity: bool
    block_b_restriction_for_pos: bool
    block_a_restriction_for_freshmen: bool
    undergrad_in_block_a_penalty: float
    pos_in_block_b_penalty: float
    waste_penalty: float
    unassigned_penalty: float
    time_limit_seconds: int
    claustrophobia_penalty: float = 0.0
    comfort_zone_min_percent: float = 0.0
    comfort_zone_max_percent: float = 0.0
    split_class_penalty: float = 0.0
    split_cohort_penalty: float = 0.0


@dataclass(frozen=True, slots=True)
class SolverResult:
    status: str  # "optimal" | "feasible" | "infeasible"
    solve_time_seconds: float
    objective_value: float
    allocations: list[tuple[int, int]]  # (group_id, room_id)
    unassigned_groups: list[int]  # group_ids
    suggestions: list[tuple[int, int, int]]  # (group_id, timeslot_id, room_id)
    solutions_found: int


# ---------------------------------------------------------------------------
# Função principal do solver unificado
# ---------------------------------------------------------------------------


def run_solver(
    config: SolverConfig,
    timeslots: list[TimeslotData],
    rooms: list[RoomData],
    groups: list[GroupData],
    callback: cp_model.CpSolverSolutionCallback | None = None,
) -> SolverResult:
    """
    Executa o solver unificado com variável Y[g, t, r].

    Cada (grupo, horário) pode receber no máximo uma sala, permitindo que uma
    turma seja dividida entre salas distintas. O modelo minimiza o custo
    composto por: grupos sem sala, divisão de turmas, divisão de coortes,
    claustrofobia e desperdício de assentos.
    """
    from app.solver.utils import build_global_minutes

    # -----------------------------------------------------------------------
    # Pré-processamento de tempo
    # -----------------------------------------------------------------------
    timeslot_dicts = [
        {"id": ts.id, "day": ts.day, "start": ts.start, "end": ts.end}
        for ts in timeslots
    ]
    global_minutes = build_global_minutes(timeslot_dicts)

    # -----------------------------------------------------------------------
    # Modelo e Solver
    # -----------------------------------------------------------------------
    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds

    # -----------------------------------------------------------------------
    # Variáveis de decisão
    # -----------------------------------------------------------------------
    Y: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for g in groups:
        for ts_id in g.timeslot_ids:
            for r in rooms:
                Y[(g.id, ts_id, r.id)] = model.NewBoolVar(f"Y_{g.id}_{ts_id}_{r.id}")

    # -----------------------------------------------------------------------
    # Restrição 1: Cada (grupo, horário) é alocado ou fica sem sala
    # -----------------------------------------------------------------------
    V: dict[tuple[int, int], cp_model.IntVar] = {}
    for g in groups:
        for ts_id in g.timeslot_ids:
            V[(g.id, ts_id)] = model.NewBoolVar(f"V_{g.id}_{ts_id}")
            model.Add(
                sum(Y[(g.id, ts_id, r.id)] for r in rooms) + V[(g.id, ts_id)] == 1
            )

    # -----------------------------------------------------------------------
    # Restrição 2: Pré-alocação (trava manual)
    # -----------------------------------------------------------------------
    for g in groups:
        if g.preassigned_room_id is not None:
            for ts_id in g.timeslot_ids:
                model.Add(Y[(g.id, ts_id, g.preassigned_room_id)] == 1)

    # -----------------------------------------------------------------------
    # Restrição 2.5: Salas bloqueadas para distribuição automática
    # -----------------------------------------------------------------------
    for g in groups:
        if g.preassigned_room_id is None:  # Turma automática
            for r in rooms:
                if not r.available_for_auto:
                    for ts_id in g.timeslot_ids:
                        model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 3: Conflitos de horário (AddNoOverlap)
    # -----------------------------------------------------------------------
    room_intervals: dict[int, list[cp_model.IntervalVar]] = {r.id: [] for r in rooms}

    for g in groups:
        for ts_id in g.timeslot_ids:
            start_global, end_global = global_minutes[ts_id]
            size = end_global - start_global

            for r in rooms:
                interval = model.NewOptionalIntervalVar(
                    start=start_global,
                    size=size,
                    end=end_global,
                    is_present=Y[(g.id, ts_id, r.id)],
                    name=f"interval_g{g.id}_r{r.id}_t{ts_id}",
                )
                room_intervals[r.id].append(interval)

    for r in rooms:
        if room_intervals[r.id]:
            model.AddNoOverlap(room_intervals[r.id])

    # -----------------------------------------------------------------------
    # Restrição 4: Capacidade da sala
    # -----------------------------------------------------------------------
    if config.strict_capacity:
        for g in groups:
            if not g.has_null_enrollment:
                for r in rooms:
                    if g.preassigned_room_id == r.id:
                        continue
                    if r.capacity < g.demand:
                        for ts_id in g.timeslot_ids:
                            model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 5: Regra do Bloco B
    # -----------------------------------------------------------------------
    if config.block_b_restriction_for_pos:
        for g in groups:
            if _sanitize_tiptur(g.tiptur) == "pos graduacao":
                for r in rooms:
                    if g.preassigned_room_id == r.id:
                        continue
                    if r.name.strip().upper().startswith("B"):
                        for ts_id in g.timeslot_ids:
                            model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 5.5: Proteção de Calouros no Bloco A
    # -----------------------------------------------------------------------
    if config.block_a_restriction_for_freshmen:
        for g in groups:
            if g.is_freshmen:
                for r in rooms:
                    if g.preassigned_room_id == r.id:
                        continue
                    if r.name.strip().upper().startswith("A"):
                        for ts_id in g.timeslot_ids:
                            model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 6: Coortes (same_room_cohort) — Soft Constraint
    # -----------------------------------------------------------------------
    cohort_groups: dict[str, list[GroupData]] = {}
    for g in groups:
        if g.same_room_cohort is not None:
            cohort_groups.setdefault(g.same_room_cohort, []).append(g)

    cost_cohort_split = 0
    split_cohort_penalty_int = int(config.split_cohort_penalty * SCALE)

    for cohort, members in cohort_groups.items():
        if len(members) < 2:
            continue

        # Z[cohort, r] = 1 se algum grupo do coorte usar a sala r.
        Z: dict[int, cp_model.IntVar] = {}
        for r in rooms:
            Z[r.id] = model.NewBoolVar(f"Z_{cohort}_{r.id}")

            for g in members:
                for ts_id in g.timeslot_ids:
                    model.Add(Z[r.id] >= Y[(g.id, ts_id, r.id)])

            model.Add(
                Z[r.id]
                <= sum(
                    Y[(g.id, ts_id, r.id)] for g in members for ts_id in g.timeslot_ids
                )
            )

        num_rooms_used = sum(Z[r.id] for r in rooms)
        extra_rooms = model.NewIntVar(0, len(rooms), f"extra_rooms_{cohort}")
        model.Add(extra_rooms >= num_rooms_used - 1)
        model.Add(extra_rooms >= 0)

        cost_cohort_split += extra_rooms * split_cohort_penalty_int

    # -----------------------------------------------------------------------
    # Restrição 7: Split Class — Soft Constraint
    # -----------------------------------------------------------------------
    cost_class_split = 0
    split_class_penalty_int = int(config.split_class_penalty * SCALE)

    for g in groups:
        # Z_class[g, r] = 1 se o grupo usar a sala r em algum horário.
        Z_class: dict[int, cp_model.IntVar] = {}
        for r in rooms:
            Z_class[r.id] = model.NewBoolVar(f"Z_class_{g.id}_{r.id}")

            for ts_id in g.timeslot_ids:
                model.Add(Z_class[r.id] >= Y[(g.id, ts_id, r.id)])

            model.Add(
                Z_class[r.id] <= sum(Y[(g.id, ts_id, r.id)] for ts_id in g.timeslot_ids)
            )

        num_rooms_used = sum(Z_class[r.id] for r in rooms)
        extra_rooms = model.NewIntVar(0, len(rooms), f"extra_class_{g.id}")
        model.Add(extra_rooms >= num_rooms_used - 1)
        model.Add(extra_rooms >= 0)

        cost_class_split += extra_rooms * split_class_penalty_int

    # -----------------------------------------------------------------------
    # Função Objetivo (com SCALE para evitar floats no CP-SAT)
    # -----------------------------------------------------------------------
    unassigned_penalty_int = int(config.unassigned_penalty * SCALE)
    claustrophobia_penalty_int = int(config.claustrophobia_penalty * SCALE)
    waste_penalty_int = int(config.waste_penalty * SCALE)

    max_ts = max((len(g.timeslot_ids) for g in groups), default=1)
    # A penalidade por horário sem sala é proporcional à penalidade de grupo
    # sem sala, garantindo que deixar todos os horários de um grupo sem sala
    # custe pelo menos `unassigned_penalty`.
    slot_unassigned_penalty_int = (unassigned_penalty_int + max_ts - 1) // max_ts

    cost_unassigned = sum(
        V[(g.id, ts_id)]
        * slot_unassigned_penalty_int
        * (1000 if g.same_room_cohort else 1)
        for g in groups
        for ts_id in g.timeslot_ids
    )

    # -----------------------------------------------------------------------
    # Função Objetivo Piecewise (ocupação de salas)
    # -----------------------------------------------------------------------
    cost_piecewise = 0
    for g in groups:
        for r in rooms:
            if r.capacity == 0:
                continue

            free_seats = r.capacity - g.demand
            free_seats_min = int(r.capacity * config.comfort_zone_min_percent / 100)
            free_seats_max = int(r.capacity * config.comfort_zone_max_percent / 100)

            slots_for_room = sum(Y[(g.id, ts_id, r.id)] for ts_id in g.timeslot_ids)

            if free_seats < free_seats_min:
                max_comfort_demand = r.capacity - free_seats_min
                excess = max(0, g.demand - max_comfort_demand)
                cost_piecewise += slots_for_room * excess * claustrophobia_penalty_int
            elif free_seats > free_seats_max:
                min_comfort_demand = r.capacity - free_seats_max
                excess = max(0, min_comfort_demand - g.demand)
                cost_piecewise += slots_for_room * excess * waste_penalty_int
            # else: dentro da zona de conforto, custo = 0

    # -----------------------------------------------------------------------
    # Penalidades Direcionais (Soft Constraints)
    # -----------------------------------------------------------------------
    undergrad_penalty_int = int(config.undergrad_in_block_a_penalty * SCALE)
    pos_penalty_int = int(config.pos_in_block_b_penalty * SCALE)

    cost_directional = 0
    for g in groups:
        tipo = _sanitize_tiptur(g.tiptur)
        for r in rooms:
            for ts_id in g.timeslot_ids:
                if tipo == "graduacao" and r.name.strip().upper().startswith("A"):
                    cost_directional += Y[(g.id, ts_id, r.id)] * undergrad_penalty_int
                if tipo == "pos graduacao" and r.name.strip().upper().startswith("B"):
                    cost_directional += Y[(g.id, ts_id, r.id)] * pos_penalty_int

    model.Minimize(
        cost_unassigned
        + cost_piecewise
        + cost_directional
        + cost_cohort_split
        + cost_class_split
    )

    # -----------------------------------------------------------------------
    # Resolver
    # -----------------------------------------------------------------------
    start_solve = time.time()
    if callback is not None:
        status = solver.Solve(model, callback)
    else:
        status = solver.Solve(model)
    solve_time = time.time() - start_solve

    # -----------------------------------------------------------------------
    # Mapear status
    # -----------------------------------------------------------------------
    if status == cp_model.OPTIMAL:
        result_status = "optimal"
    elif status == cp_model.FEASIBLE:
        result_status = "feasible"
    elif status == cp_model.INFEASIBLE:
        result_status = "infeasible"
    else:
        raise SolverException(
            f"Status inesperado do CP-SAT: {status} ({solver.StatusName(status)})"
        )

    if result_status == "infeasible":
        return SolverResult(
            status="infeasible",
            solve_time_seconds=solve_time,
            objective_value=0.0,
            allocations=[],
            unassigned_groups=[],
            suggestions=[],
            solutions_found=0,
        )

    # -----------------------------------------------------------------------
    # Extrair resultados
    # -----------------------------------------------------------------------
    allocations: list[tuple[int, int]] = []
    unassigned_groups: list[int] = []
    suggestions: list[tuple[int, int, int]] = []

    for g in groups:
        assigned_slots: list[tuple[int, int]] = []
        for ts_id in g.timeslot_ids:
            for r in rooms:
                if solver.Value(Y[(g.id, ts_id, r.id)]) == 1:
                    assigned_slots.append((ts_id, r.id))
                    break

        if not assigned_slots:
            unassigned_groups.append(g.id)
            continue

        unique_rooms = {r_id for _, r_id in assigned_slots}
        fully_assigned = len(assigned_slots) == len(g.timeslot_ids)

        if fully_assigned and len(unique_rooms) == 1:
            allocations.append((g.id, unique_rooms.pop()))
        else:
            unassigned_groups.append(g.id)
            for ts_id, r_id in assigned_slots:
                suggestions.append((g.id, ts_id, r_id))

    raw_objective = solver.ObjectiveValue() if hasattr(solver, "ObjectiveValue") else 0
    # Desescalar para retornar valor próximo ao original
    objective_value = float(raw_objective) / SCALE

    solutions_found = callback.solution_count if callback else 1

    return SolverResult(
        status=result_status,
        solve_time_seconds=solve_time,
        objective_value=objective_value,
        allocations=allocations,
        unassigned_groups=unassigned_groups,
        suggestions=suggestions,
        solutions_found=solutions_found,
    )


class SolverException(Exception):
    """Exceção levantada quando o solver retorna um estado inesperado."""
