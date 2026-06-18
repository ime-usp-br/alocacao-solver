#!/usr/bin/env python3
"""Script de calibração de pesos do solver via Optuna.

Este script carrega payloads JSON reais de semestres anteriores, executa o
solver CP-SAT com diferentes combinações de pesos e utiliza o Optuna para
encontrar a configuração que melhor respeita a hierarquia lexicográfica de
violações:

    unassigned > split_class > split_cohort > claustrofobia > waste

Uso:
    poetry run python scripts/optuna_calibrate.py \
        --payload-dir tmp/optuna_payloads \
        --n-trials 30 \
        --time-limit 30
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

# Permite executar o script diretamente sem instalar o pacote.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import optuna  # noqa: E402

from app.api.schemas import Group, Room, Timeslot  # noqa: E402
from app.solver.engine import (  # noqa: E402
    GroupData,
    RoomData,
    SolverConfig,
    SolverResult,
    TimeslotData,
    run_solver,
)
from app.worker.processor import (  # noqa: E402
    _to_internal_config,
    _to_internal_groups,
    _to_internal_rooms,
    _to_internal_timeslots,
)

# Pesos astronômicos fixos usados pelo meta-score para avaliar a qualidade real
# da solução. Mantêm a ordem lexicográfica independentemente dos pesos que o
# Optuna está calibrando.
META_UNASSIGNED_WEIGHT = 1_000_000_000
META_SPLIT_CLASS_WEIGHT = 1_000_000
META_SPLIT_COHORT_WEIGHT = 1_000
META_CLAUSTROPHOBIA_WEIGHT = 100
META_WASTE_WEIGHT = 1

# Pesos padrão que não fazem parte da otimização (mantidos do payload).
DEFAULT_DIRECTIONAL_PENALTIES = {
    "undergrad_in_block_a_penalty": 500.0,
    "pos_in_block_b_penalty": 500.0,
}


def load_payloads(payload_dir: Path) -> list[dict[str, Any]]:
    """Carrega todos os arquivos JSON do diretório de payloads."""
    payloads: list[dict[str, Any]] = []
    for path in sorted(payload_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                payloads.append(json.load(fh))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Aviso: ignorando payload {path}: {exc}", file=sys.stderr)
    if not payloads:
        raise ValueError(f"Nenhum payload JSON encontrado em {payload_dir}")
    return payloads


def _convert_payload(
    payload: dict[str, Any],
) -> tuple[SolverConfig, list[TimeslotData], list[RoomData], list[GroupData]]:
    """Converte um payload JSON branco nas estruturas internas do solver."""
    # Usa o schema Pydantic para validação e conversão, depois traduz para as
    # estruturas internas reutilizando os helpers do worker.
    request_config = {
        "strict_capacity": payload["config"]["strict_capacity"],
        "block_b_restriction_for_pos": payload["config"]["block_b_restriction_for_pos"],
        "block_a_restriction_for_freshmen": payload["config"][
            "block_a_restriction_for_freshmen"
        ],
        "undergrad_in_block_a_penalty": payload["config"].get(
            "undergrad_in_block_a_penalty",
            DEFAULT_DIRECTIONAL_PENALTIES["undergrad_in_block_a_penalty"],
        ),
        "pos_in_block_b_penalty": payload["config"].get(
            "pos_in_block_b_penalty",
            DEFAULT_DIRECTIONAL_PENALTIES["pos_in_block_b_penalty"],
        ),
        "waste_penalty": payload["config"]["waste_penalty"],
        "claustrophobia_penalty": payload["config"]["claustrophobia_penalty"],
        "comfort_zone_min_percent": payload["config"]["comfort_zone_min_percent"],
        "comfort_zone_max_percent": payload["config"]["comfort_zone_max_percent"],
        "split_class_penalty": payload["config"]["split_class_penalty"],
        "split_cohort_penalty": payload["config"]["split_cohort_penalty"],
        "unassigned_penalty": payload["config"]["unassigned_penalty"],
        "time_limit_seconds": payload["config"]["time_limit_seconds"],
    }

    request_timeslots = [Timeslot.model_validate(ts) for ts in payload["timeslots"]]
    request_rooms = [Room.model_validate(r) for r in payload["rooms"]]
    request_groups = [Group.model_validate(g) for g in payload["groups"]]

    class DummyRequest:
        def __init__(self, config_obj: Any) -> None:
            self.config = config_obj

    config = _to_internal_config(DummyRequest(type("Config", (), request_config)()))
    timeslots = _to_internal_timeslots(request_timeslots)
    rooms = _to_internal_rooms(request_rooms)
    groups = _to_internal_groups(request_groups)

    return config, timeslots, rooms, groups


def count_split_classes(result: SolverResult) -> int:
    """Conta quantas turmas estão divididas entre duas ou mais salas."""
    rooms_by_group: dict[int, set[int]] = {}
    for group_id, _, room_id in result.suggestions:
        rooms_by_group.setdefault(group_id, set()).add(room_id)
    return sum(1 for rooms in rooms_by_group.values() if len(rooms) > 1)


def count_split_cohorts(result: SolverResult, groups: list[GroupData]) -> int:
    """Conta quantos coortes estão divididos entre duas ou mais salas."""
    cohort_members: dict[str, list[int]] = {}
    for g in groups:
        if g.same_room_cohort is not None:
            cohort_members.setdefault(g.same_room_cohort, []).append(g.id)

    if not cohort_members:
        return 0

    rooms_by_group = _rooms_used_by_group(result)

    split_cohorts = 0
    for cohort, member_ids in cohort_members.items():
        used_rooms: set[int] = set()
        for group_id in member_ids:
            used_rooms.update(rooms_by_group.get(group_id, set()))
        if len(used_rooms) > 1:
            split_cohorts += 1

    return split_cohorts


def _rooms_used_by_group(result: SolverResult) -> dict[int, set[int]]:
    """Mapeia group_id -> conjunto de salas efetivamente utilizadas."""
    rooms_by_group: dict[int, set[int]] = {}
    for group_id, room_id in result.allocations:
        rooms_by_group.setdefault(group_id, set()).add(room_id)
    for group_id, _, room_id in result.suggestions:
        rooms_by_group.setdefault(group_id, set()).add(room_id)
    return rooms_by_group


def _iter_assigned_slots(
    result: SolverResult, groups: list[GroupData], rooms: list[RoomData]
) -> list[tuple[int, int, int]]:
    """Retorna lista de (group_id, room_id, number_of_slots)."""
    group_timeslots = {g.id: len(g.timeslot_ids) for g in groups}

    assignments: list[tuple[int, int, int]] = []
    for group_id, room_id in result.allocations:
        assignments.append((group_id, room_id, group_timeslots.get(group_id, 1)))

    suggestions_count: dict[tuple[int, int], int] = {}
    for group_id, _, room_id in result.suggestions:
        suggestions_count[(group_id, room_id)] = (
            suggestions_count.get((group_id, room_id), 0) + 1
        )

    for (group_id, room_id), count in suggestions_count.items():
        assignments.append((group_id, room_id, count))

    return assignments


def calc_claustrophobia(
    result: SolverResult,
    rooms: list[RoomData],
    groups: list[GroupData],
    comfort_zone_min_percent: float,
) -> int:
    """Soma os pontos de claustrofobia reais da solução."""
    group_demand = {g.id: g.demand for g in groups}
    total = 0
    for group_id, room_id, slots in _iter_assigned_slots(result, groups, rooms):
        room = next((r for r in rooms if r.id == room_id), None)
        if room is None or room.capacity == 0:
            continue
        demand = group_demand.get(group_id, 0)
        free_seats_min = int(room.capacity * comfort_zone_min_percent / 100)
        free_seats = room.capacity - demand
        if free_seats < free_seats_min:
            max_comfort_demand = room.capacity - free_seats_min
            excess = max(0, demand - max_comfort_demand)
            total += excess * slots
    return total


def calc_waste(
    result: SolverResult,
    rooms: list[RoomData],
    groups: list[GroupData],
    comfort_zone_max_percent: float,
) -> int:
    """Soma os pontos de desperdício reais da solução."""
    group_demand = {g.id: g.demand for g in groups}
    total = 0
    for group_id, room_id, slots in _iter_assigned_slots(result, groups, rooms):
        room = next((r for r in rooms if r.id == room_id), None)
        if room is None or room.capacity == 0:
            continue
        demand = group_demand.get(group_id, 0)
        free_seats_max = int(room.capacity * comfort_zone_max_percent / 100)
        free_seats = room.capacity - demand
        if free_seats > free_seats_max:
            min_comfort_demand = room.capacity - free_seats_max
            excess = max(0, min_comfort_demand - demand)
            total += excess * slots
    return total


def build_meta_score(
    result: SolverResult,
    rooms: list[RoomData],
    groups: list[GroupData],
    comfort_min: float,
    comfort_max: float,
) -> int:
    """Calcula o meta-score de uma solução usando pesos fixos astronômicos."""
    qtd_unassigned = len(result.unassigned_groups)
    qtd_split_class = count_split_classes(result)
    qtd_split_cohort = count_split_cohorts(result, groups)
    pontos_claustrofobia = calc_claustrophobia(result, rooms, groups, comfort_min)
    pontos_waste = calc_waste(result, rooms, groups, comfort_max)

    return (
        qtd_unassigned * META_UNASSIGNED_WEIGHT
        + qtd_split_class * META_SPLIT_CLASS_WEIGHT
        + qtd_split_cohort * META_SPLIT_COHORT_WEIGHT
        + pontos_claustrofobia * META_CLAUSTROPHOBIA_WEIGHT
        + pontos_waste * META_WASTE_WEIGHT
    )


def objective(
    trial: optuna.Trial,
    payloads: list[dict[str, Any]],
    time_limit_seconds: int,
    progress_every: int,
) -> float:
    """Função objetivo do Optuna.

    O espaço de busca é construído de forma a preservar a hierarquia
    lexicográfica das penalidades.
    """
    # 1. Espaço de busca hierárquico.
    config_weights = {
        "waste_penalty": 1.0,
        "claustrophobia_penalty": float(
            trial.suggest_int("claustrophobia_penalty", 2, 100)
        ),
        "split_cohort_penalty": float(
            trial.suggest_int("split_cohort_penalty", 500, 10_000)
        ),
        "split_class_penalty": float(
            trial.suggest_int("split_class_penalty", 20_000, 100_000)
        ),
        "unassigned_penalty": float(
            trial.suggest_int("unassigned_penalty", 500_000, 5_000_000)
        ),
    }

    total_meta_score = 0.0
    total_solve_time = 0.0
    evaluated = 0

    for idx, payload in enumerate(payloads):
        # Sobrescreve apenas os pesos que estamos calibrando.
        payload["config"].update(config_weights)
        payload["config"]["time_limit_seconds"] = time_limit_seconds

        config, timeslots, rooms, groups = _convert_payload(payload)

        try:
            result = run_solver(config, timeslots, rooms, groups)
        except Exception as exc:  # pragma: no cover - falhas graves são punidas
            print(
                f"Trial {trial.number} falhou no payload {idx}: {exc}", file=sys.stderr
            )
            traceback.print_exc(file=sys.stderr)
            return float("inf")

        meta_score = build_meta_score(
            result,
            rooms,
            groups,
            config.comfort_zone_min_percent,
            config.comfort_zone_max_percent,
        )
        total_meta_score += meta_score
        total_solve_time += result.solve_time_seconds
        evaluated += 1

        if progress_every > 0 and (idx + 1) % progress_every == 0:
            print(
                f"  Trial {trial.number}: processados {idx + 1}/{len(payloads)} payloads"
            )

    if evaluated == 0:
        return float("inf")

    average_meta_score = total_meta_score / evaluated
    average_time = total_solve_time / evaluated

    # Minimiza violações; tempo serve apenas como critério de desempate.
    return average_meta_score + (average_time * 0.1)


def run_calibration(
    payload_dir: Path,
    n_trials: int,
    time_limit_seconds: int,
    n_jobs: int,
    seed: int | None,
    study_name: str,
    storage: str | None,
) -> dict[str, float]:
    """Executa o estudo do Optuna e retorna os melhores pesos encontrados."""
    payloads = load_payloads(payload_dir)
    print(f"Carregados {len(payloads)} payloads de {payload_dir}")

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        study_name=study_name,
        storage=storage,
        load_if_exists=True,
    )

    progress_every = max(1, len(payloads) // 2)

    def _objective(trial: optuna.Trial) -> float:
        return objective(trial, payloads, time_limit_seconds, progress_every)

    study.optimize(_objective, n_trials=n_trials, n_jobs=n_jobs, show_progress_bar=True)

    best = study.best_params
    best_weights = {
        "waste_penalty": 1.0,
        "claustrophobia_penalty": float(best["claustrophobia_penalty"]),
        "split_cohort_penalty": float(best["split_cohort_penalty"]),
        "split_class_penalty": float(best["split_class_penalty"]),
        "unassigned_penalty": float(best["unassigned_penalty"]),
    }

    return best_weights


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Calibração automática dos pesos do solver de alocação de salas."
    )
    parser.add_argument(
        "--payload-dir",
        type=Path,
        default=Path("tmp/optuna_payloads"),
        help="Diretório com os payloads JSON (default: tmp/optuna_payloads).",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=30,
        help="Número de trials do Optuna (default: 30).",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=30,
        help="Tempo limite do solver em segundos para cada payload (default: 30).",
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="Número de jobs paralelos do Optuna (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed para reprodutibilidade do sampler TPE.",
    )
    parser.add_argument(
        "--study-name",
        type=str,
        default="alocacao-solver-weight-calibration",
        help="Nome do estudo do Optuna.",
    )
    parser.add_argument(
        "--storage",
        type=str,
        default=None,
        help="URL de storage do Optuna (ex: sqlite:///tmp/optuna.db).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tmp/optuna_best_weights.json"),
        help="Caminho para salvar os pesos recomendados (default: tmp/optuna_best_weights.json).",
    )

    args = parser.parse_args(argv)

    best_weights = run_calibration(
        payload_dir=args.payload_dir,
        n_trials=args.n_trials,
        time_limit_seconds=args.time_limit,
        n_jobs=args.n_jobs,
        seed=args.seed,
        study_name=args.study_name,
        storage=args.storage,
    )

    output_data = {
        "weights": best_weights,
        "hierarchy": [
            "unassigned_penalty",
            "split_class_penalty",
            "split_cohort_penalty",
            "claustrophobia_penalty",
            "waste_penalty",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        json.dump(output_data, fh, indent=2, ensure_ascii=False)

    print("\n=== Pesos recomendados ===")
    for key, value in best_weights.items():
        print(f"  {key}: {value}")
    print(f"\nSalvo em: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
