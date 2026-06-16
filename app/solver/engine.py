"""Motor matemático do Passe 1 (Alocação Estrita) usando OR-Tools CP-SAT."""

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
    wasted_seats_weight: float
    unassigned_penalty: float
    time_limit_seconds: int


@dataclass(frozen=True, slots=True)
class Pass1Result:
    status: str  # "optimal" | "feasible" | "infeasible"
    solve_time_seconds: float
    objective_value: float
    allocations: list[tuple[int, int]]  # (group_id, room_id)
    unassigned_groups: list[int]  # group_ids
    solutions_found: int


@dataclass(frozen=True, slots=True)
class Pass2Result:
    status: str  # "optimal" | "feasible" | "infeasible" | "skipped"
    solve_time_seconds: float
    suggestions: list[tuple[int, int, int]]  # (group_id, timeslot_id, room_id)
    solutions_found: int


# ---------------------------------------------------------------------------
# Função principal do Passe 1
# ---------------------------------------------------------------------------


def run_pass_1(
    config: SolverConfig,
    timeslots: list[TimeslotData],
    rooms: list[RoomData],
    groups: list[GroupData],
    callback: cp_model.CpSolverSolutionCallback | None = None,
) -> Pass1Result:
    """
    Executa o Passe 1 de alocação estrita.

    Cada grupo recebe exatamente uma sala (ou fica unassigned).
    Conflitos de horário são resolvidos via AddNoOverlap com
    NewOptionalIntervalVar para performance O(N log N).
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
    X: dict[tuple[int, int], cp_model.IntVar] = {}
    for g in groups:
        for r in rooms:
            X[(g.id, r.id)] = model.NewBoolVar(f"X_{g.id}_{r.id}")

    U: dict[int, cp_model.IntVar] = {}
    for g in groups:
        U[g.id] = model.NewBoolVar(f"U_{g.id}")

    # -----------------------------------------------------------------------
    # Restrição 1: Atribuição única
    # -----------------------------------------------------------------------
    for g in groups:
        model.Add(sum(X[(g.id, r.id)] for r in rooms) + U[g.id] == 1)

    # -----------------------------------------------------------------------
    # Restrição 2: Pré-alocação (trava manual)
    # -----------------------------------------------------------------------
    for g in groups:
        if g.preassigned_room_id is not None:
            model.Add(X[(g.id, g.preassigned_room_id)] == 1)

    # -----------------------------------------------------------------------
    # Restrição 2.5: Salas bloqueadas para distribuição automática
    # -----------------------------------------------------------------------
    for g in groups:
        if g.preassigned_room_id is None:  # Turma automática
            for r in rooms:
                if not r.available_for_auto:
                    model.Add(X[(g.id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 3: Conflitos de horário (AddNoOverlap)
    # -----------------------------------------------------------------------
    room_intervals: dict[int, list[cp_model.IntervalVar]] = {r.id: [] for r in rooms}

    for g in groups:
        for r in rooms:
            for ts_id in g.timeslot_ids:
                start_global, end_global = global_minutes[ts_id]
                size = end_global - start_global

                interval = model.NewOptionalIntervalVar(
                    start=start_global,
                    size=size,
                    end=end_global,
                    is_present=X[(g.id, r.id)],
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
                    if r.capacity < g.demand:
                        # Sala é muito pequena: forçar X == 0
                        model.Add(X[(g.id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 5: Regra do Bloco B
    # -----------------------------------------------------------------------
    if config.block_b_restriction_for_pos:
        for g in groups:
            if _sanitize_tiptur(g.tiptur) == "pos graduacao":
                for r in rooms:
                    if r.name.strip().upper().startswith("B"):
                        model.Add(X[(g.id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 5.5: Proteção de Calouros no Bloco A
    # -----------------------------------------------------------------------
    if config.block_a_restriction_for_freshmen:
        for g in groups:
            if g.is_freshmen:
                for r in rooms:
                    if r.name.strip().upper().startswith("A"):
                        model.Add(X[(g.id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 6: Mesma Sala para Coortes (same_room_cohort)
    # -----------------------------------------------------------------------
    cohort_groups: dict[str, list[GroupData]] = {}
    for g in groups:
        if g.same_room_cohort is not None:
            cohort_groups.setdefault(g.same_room_cohort, []).append(g)

    for cohort, members in cohort_groups.items():
        if len(members) < 2:
            continue
        g_anchor = members[0]
        for g_i in members[1:]:
            for r in rooms:
                model.Add(X[(g_anchor.id, r.id)] == X[(g_i.id, r.id)])

    # -----------------------------------------------------------------------
    # Função Objetivo (com SCALE para evitar floats no CP-SAT)
    # -----------------------------------------------------------------------
    unassigned_penalty_int = int(config.unassigned_penalty * SCALE)
    wasted_seats_weight_int = int(config.wasted_seats_weight * SCALE)

    cost_unassigned = sum(
        U[g.id] * unassigned_penalty_int * (1000 if g.same_room_cohort else 1)
        for g in groups
    )

    cost_waste = 0
    for g in groups:
        for r in rooms:
            waste = max(0, r.capacity - g.demand)
            if waste > 0:
                cost_waste += X[(g.id, r.id)] * waste * wasted_seats_weight_int

    # -----------------------------------------------------------------------
    # Penalidades Direcionais (Soft Constraints)
    # -----------------------------------------------------------------------
    undergrad_penalty_int = int(config.undergrad_in_block_a_penalty * SCALE)
    pos_penalty_int = int(config.pos_in_block_b_penalty * SCALE)

    cost_directional = 0
    for g in groups:
        tipo = _sanitize_tiptur(g.tiptur)
        for r in rooms:
            if tipo == "graduacao" and r.name.strip().upper().startswith("A"):
                cost_directional += X[(g.id, r.id)] * undergrad_penalty_int
            if tipo == "pos graduacao" and r.name.strip().upper().startswith("B"):
                cost_directional += X[(g.id, r.id)] * pos_penalty_int

    model.Minimize(cost_unassigned + cost_waste + cost_directional)

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
        return Pass1Result(
            status="infeasible",
            solve_time_seconds=solve_time,
            objective_value=0.0,
            allocations=[],
            unassigned_groups=[],
            solutions_found=0,
        )

    # -----------------------------------------------------------------------
    # Extrair resultados
    # -----------------------------------------------------------------------
    allocations: list[tuple[int, int]] = []
    unassigned_groups: list[int] = []

    for g in groups:
        assigned = False
        for r in rooms:
            if solver.Value(X[(g.id, r.id)]) == 1:
                allocations.append((g.id, r.id))
                assigned = True
                break
        if not assigned:
            unassigned_groups.append(g.id)

    raw_objective = solver.ObjectiveValue() if hasattr(solver, "ObjectiveValue") else 0
    # Desescalar para retornar valor próximo ao original
    objective_value = float(raw_objective) / SCALE

    solutions_found = callback.solution_count if callback else 1

    return Pass1Result(
        status=result_status,
        solve_time_seconds=solve_time,
        objective_value=objective_value,
        allocations=allocations,
        unassigned_groups=unassigned_groups,
        solutions_found=solutions_found,
    )


def run_pass_2(
    config: SolverConfig,
    timeslots: list[TimeslotData],
    rooms: list[RoomData],
    groups: list[GroupData],
    pass1_allocations: list[tuple[int, int]],
    pass1_unassigned_groups: list[int],
    callback: cp_model.CpSolverSolutionCallback | None = None,
) -> Pass2Result:
    """
    Executa o Passe 2 de sugestão de quebras de horários (Best Effort).

    Grupos que ficaram unassigned no Passe 1 podem ser alocados em salas
    diferentes para cada timeslot. O modelo maximiza o número de alocações
    e, entre soluções equivalentes, minimiza o desperdício de assentos.

    Nota sobre coortes (same_room_cohort):
    A restrição de "mesma sala" é intencionalmente relaxada no Passe 2.
    Se uma coorte chegou ao Passe 2 como unassigned, é prova matemática
    de que não existe nenhuma sala viável para todos os seus horários
    simultaneamente. O Passe 2 atua como fallback de resgate, permitindo
    quebra de horários, mas mantém prioridade absoluta para grupos de
    coorte via multiplicador agressivo na recompensa (reward_g).
    """
    from app.solver.utils import build_global_minutes

    if not pass1_unassigned_groups:
        return Pass2Result(
            status="skipped",
            solve_time_seconds=0.0,
            suggestions=[],
            solutions_found=0,
        )

    # -----------------------------------------------------------------------
    # Pré-processamento de tempo
    # -----------------------------------------------------------------------
    timeslot_dicts = [
        {"id": ts.id, "day": ts.day, "start": ts.start, "end": ts.end}
        for ts in timeslots
    ]
    global_minutes = build_global_minutes(timeslot_dicts)

    # -----------------------------------------------------------------------
    # Mapeamentos rápidos
    # -----------------------------------------------------------------------
    group_by_id: dict[int, GroupData] = {g.id: g for g in groups}
    g_unassigned = [
        group_by_id[g_id] for g_id in pass1_unassigned_groups if g_id in group_by_id
    ]

    # -----------------------------------------------------------------------
    # Modelo e Solver
    # -----------------------------------------------------------------------
    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_seconds

    # -----------------------------------------------------------------------
    # Intervalos FIXOS do Passe 1 (ocupam tempo fisicamente)
    # -----------------------------------------------------------------------
    room_intervals: dict[int, list[cp_model.IntervalVar]] = {r.id: [] for r in rooms}

    for g_id, r_id in pass1_allocations:
        g = group_by_id.get(g_id)
        if g is None:
            continue
        for ts_id in g.timeslot_ids:
            start_global, end_global = global_minutes[ts_id]
            size = end_global - start_global
            fixed_interval = model.NewIntervalVar(
                start=start_global,
                size=size,
                end=end_global,
                name=f"fixed_g{g_id}_r{r_id}_t{ts_id}",
            )
            room_intervals[r_id].append(fixed_interval)

    # -----------------------------------------------------------------------
    # Variáveis de decisão Y[g, t, r]
    # -----------------------------------------------------------------------
    Y: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for g in g_unassigned:
        for ts_id in g.timeslot_ids:
            for r in rooms:
                Y[(g.id, ts_id, r.id)] = model.NewBoolVar(f"Y_{g.id}_{ts_id}_{r.id}")

    # -----------------------------------------------------------------------
    # Restrição 1: No máximo 1 sala por timeslot (Best Effort)
    # -----------------------------------------------------------------------
    for g in g_unassigned:
        for ts_id in g.timeslot_ids:
            model.Add(sum(Y[(g.id, ts_id, r.id)] for r in rooms) <= 1)

    # -----------------------------------------------------------------------
    # Restrição 2: AddNoOverlap (fixos + opcionais do Passe 2)
    # -----------------------------------------------------------------------
    for g in g_unassigned:
        for r in rooms:
            for ts_id in g.timeslot_ids:
                start_global, end_global = global_minutes[ts_id]
                size = end_global - start_global
                optional_interval = model.NewOptionalIntervalVar(
                    start=start_global,
                    size=size,
                    end=end_global,
                    is_present=Y[(g.id, ts_id, r.id)],
                    name=f"opt_g{g.id}_r{r.id}_t{ts_id}",
                )
                room_intervals[r.id].append(optional_interval)

    for r in rooms:
        if room_intervals[r.id]:
            model.AddNoOverlap(room_intervals[r.id])

    # -----------------------------------------------------------------------
    # Restrição 3: Capacidade da sala
    # -----------------------------------------------------------------------
    if config.strict_capacity:
        for g in g_unassigned:
            if not g.has_null_enrollment:
                for r in rooms:
                    if r.capacity < g.demand:
                        for ts_id in g.timeslot_ids:
                            model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 4: Regra do Bloco B
    # -----------------------------------------------------------------------
    if config.block_b_restriction_for_pos:
        for g in g_unassigned:
            if _sanitize_tiptur(g.tiptur) == "pos graduacao":
                for r in rooms:
                    if r.name.strip().upper().startswith("B"):
                        for ts_id in g.timeslot_ids:
                            model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 4.5: Proteção de Calouros no Bloco A
    # -----------------------------------------------------------------------
    if config.block_a_restriction_for_freshmen:
        for g in g_unassigned:
            if g.is_freshmen:
                for r in rooms:
                    if r.name.strip().upper().startswith("A"):
                        for ts_id in g.timeslot_ids:
                            model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Restrição 4.6: Salas bloqueadas para distribuição automática
    # -----------------------------------------------------------------------
    for g in g_unassigned:
        for r in rooms:
            if not r.available_for_auto:
                for ts_id in g.timeslot_ids:
                    model.Add(Y[(g.id, ts_id, r.id)] == 0)

    # -----------------------------------------------------------------------
    # Função Objetivo: Maximizar alocações (via recompensa gigante)
    # -----------------------------------------------------------------------
    wasted_seats_weight_int = int(config.wasted_seats_weight * SCALE)
    # Recompensa deve ser muito maior que qualquer custo de waste possível
    max_possible_waste = max(r.capacity for r in rooms) * wasted_seats_weight_int
    reward = max_possible_waste + (10_000_000 * SCALE)

    cost = 0
    for g in g_unassigned:
        reward_g = reward * (1000 if g.same_room_cohort else 1)
        for ts_id in g.timeslot_ids:
            for r in rooms:
                waste = max(0, r.capacity - g.demand)
                # Minimizar (waste - reward_g) quando Y == 1
                # Como reward_g >> waste, isso efetivamente maximiza Y
                coeff = (waste * wasted_seats_weight_int) - reward_g
                cost += Y[(g.id, ts_id, r.id)] * coeff

    # -----------------------------------------------------------------------
    # Penalidades Direcionais no Passe 2 (Soft Constraints)
    # -----------------------------------------------------------------------
    undergrad_penalty_int = int(config.undergrad_in_block_a_penalty * SCALE)
    pos_penalty_int = int(config.pos_in_block_b_penalty * SCALE)

    for g in g_unassigned:
        tipo = _sanitize_tiptur(g.tiptur)
        for r in rooms:
            if tipo == "graduacao" and r.name.strip().upper().startswith("A"):
                for ts_id in g.timeslot_ids:
                    cost += Y[(g.id, ts_id, r.id)] * undergrad_penalty_int
            if tipo == "pos graduacao" and r.name.strip().upper().startswith("B"):
                for ts_id in g.timeslot_ids:
                    cost += Y[(g.id, ts_id, r.id)] * pos_penalty_int

    model.Minimize(cost)

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
            f"Status inesperado do CP-SAT no Passe 2: {status} ({solver.StatusName(status)})"
        )

    if result_status == "infeasible":
        return Pass2Result(
            status="infeasible",
            solve_time_seconds=solve_time,
            suggestions=[],
            solutions_found=0,
        )

    # -----------------------------------------------------------------------
    # Extrair sugestões
    # -----------------------------------------------------------------------
    suggestions: list[tuple[int, int, int]] = []
    for g in g_unassigned:
        for ts_id in g.timeslot_ids:
            for r in rooms:
                if solver.Value(Y[(g.id, ts_id, r.id)]) == 1:
                    suggestions.append((g.id, ts_id, r.id))

    solutions_found = callback.solution_count if callback else 1

    return Pass2Result(
        status=result_status,
        solve_time_seconds=solve_time,
        suggestions=suggestions,
        solutions_found=solutions_found,
    )


class SolverException(Exception):
    """Exceção levantada quando o solver retorna um estado inesperado."""
